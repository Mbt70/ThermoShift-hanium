"""AI 분석 API.

Claude API 키는 이 서버에만 있다. 프론트는 결과만 받아간다.
키가 없으면 503을 돌려주고, 프론트는 기존 하드코딩된 설명으로 폴백한다.
"""

import json
from datetime import date, datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from ..auth import current_user, require_room_access
from ..db import get_conn
from ..services import ai, snapshot, stats
from ..services.timeutil import to_local_iso
from .control import action_label

router = APIRouter(prefix="/api/ai", tags=["ai"])

_UNAVAILABLE = "AI 기능이 설정되지 않았습니다. 서버에 ANTHROPIC_API_KEY 를 설정해 주세요."


@router.get("/status")
def status():
    return {"available": ai.is_available(), "model": ai.MODEL if ai.is_available() else None}


@router.post("/explain-decision")
def explain_decision(
    log_id: str = Query(..., description="decision:<rowid> 또는 command:<id>"),
    actor: str = Depends(current_user),
):
    if not ai.is_available():
        raise HTTPException(status_code=503, detail=_UNAVAILABLE)

    kind, _, raw_id = log_id.partition(":")
    if kind != "decision":
        raise HTTPException(status_code=400, detail="자동 제어 판단(decision:) 만 설명할 수 있습니다.")

    with get_conn() as conn:
        row = conn.execute(
            "SELECT rowid, * FROM control_decisions WHERE rowid = ?", (raw_id,)
        ).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="제어 판단을 찾을 수 없습니다.")
        require_room_access(row["room_id"], actor)
        room = conn.execute("SELECT * FROM rooms WHERE id = ?", (row["room_id"],)).fetchone()
        if room is None:
            raise HTTPException(status_code=404, detail="공간을 찾을 수 없습니다.")

        decision = {
            "timestamp": to_local_iso(row["timestamp"]),
            "control_mode": row["control_mode"],
            "content": action_label(row["proposed_action"]),
            "proposed_action": row["proposed_action"],
            "executed": bool(row["executed"]),
            "occupancy_state": row["occupancy_state"],
            "temperature": row["temperature_c"],
            "co2": row["co2_ppm"],
            "reason_codes": json.loads(row["reason_codes_json"] or "[]"),
        }
        room_payload = dict(room)

    result = ai.explain_decision(decision, room_payload)
    if result is None:
        raise HTTPException(status_code=502, detail="AI 응답을 받지 못했습니다.")
    return {"log_id": log_id, **result.model_dump()}


@router.post("/diagnose-alert")
def diagnose_alert(alert_id: str = Query(...), actor: str = Depends(current_user)):
    if not ai.is_available():
        raise HTTPException(status_code=503, detail=_UNAVAILABLE)

    with get_conn() as conn:
        row = conn.execute("SELECT * FROM alerts WHERE id = ?", (alert_id,)).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="알림을 찾을 수 없습니다.")
        require_room_access(row["room_id"], actor)
        alert = dict(row)
        alert["created_at"] = to_local_iso(alert["created_at"])

        room_id = alert["room_id"]
        room_row = conn.execute("SELECT * FROM rooms WHERE id = ?", (room_id,)).fetchone()
        payload = snapshot.build_room_payload(conn, room_row) if room_row else {}
        devices = conn.execute(
            "SELECT id, type, enabled FROM devices WHERE room_id = ?", (room_id,)
        ).fetchall()

        context = {
            "temperature": payload.get("temperature"),
            "humidity": payload.get("humidity"),
            "co2": payload.get("co2"),
            "sensor_connected": payload.get("sensor_connected"),
            "last_updated": to_local_iso(payload.get("last_updated")),
            "recent_decision": payload.get("decision"),
            "devices": [f"{d['id']}({d['type']}, {'사용' if d['enabled'] else '미사용'})" for d in devices],
        }

    result = ai.diagnose_alert(alert, context)
    if result is None:
        raise HTTPException(status_code=502, detail="AI 응답을 받지 못했습니다.")
    return {"alert_id": alert_id, **result.model_dump()}


@router.get("/stats")
def get_stats(
    room_id: str = Query(...),
    start: Optional[str] = Query(default=None, description="YYYY-MM-DD"),
    end: Optional[str] = Query(default=None, description="YYYY-MM-DD"),
    actor: str = Depends(current_user),
):
    """AI 없이 숫자만 필요할 때. 성과 리포트 화면이 쓴다."""
    require_room_access(room_id, actor)
    start_date, end_date = _parse_period(start, end)
    with get_conn() as conn:
        try:
            return stats.collect(conn, room_id, start_date, end_date)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc))


@router.post("/report")
def generate_report(
    room_id: str = Query(...),
    start: Optional[str] = Query(default=None),
    end: Optional[str] = Query(default=None),
    actor: str = Depends(current_user),
):
    """기간 KPI를 집계하고 AI 요약을 붙여 돌려준다."""
    require_room_access(room_id, actor)
    start_date, end_date = _parse_period(start, end)
    with get_conn() as conn:
        try:
            collected = stats.collect(conn, room_id, start_date, end_date)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc))

    if not ai.is_available():
        # 숫자는 그대로 주고 요약만 비운다. 화면이 빈손으로 돌아가지 않게.
        return {"stats": collected, "ai": None, "ai_unavailable_reason": _UNAVAILABLE}

    result = ai.weekly_report(collected)
    if result is None:
        return {"stats": collected, "ai": None, "ai_unavailable_reason": "AI 응답을 받지 못했습니다."}
    return {"stats": collected, "ai": result.model_dump()}


def _parse_period(start: Optional[str], end: Optional[str]) -> tuple[date, date]:
    if start is None and end is None:
        return stats.default_period()
    try:
        start_date = datetime.strptime(start, "%Y-%m-%d").date() if start else None
        end_date = datetime.strptime(end, "%Y-%m-%d").date() if end else date.today()
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="날짜 형식은 YYYY-MM-DD 입니다.")
    if start_date is None:
        start_date, _ = stats.default_period()
    if start_date > end_date:
        raise HTTPException(status_code=400, detail="시작일이 종료일보다 늦습니다.")
    return start_date, end_date
