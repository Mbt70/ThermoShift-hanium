"""제어 로그 · 제어 명령 API.

제어 로그는 두 출처를 하나로 합친다.
  1. control_decisions — gateway가 30초마다 남기는 자동 판단
  2. control_commands  — 프론트에서 사용자가 내린 수동 명령

자동 판단은 30초마다 쌓이므로 같은 판단이 이어진 구간은 하나로 접는다.
(윈도우 함수 LAG로 직전 행과 액션이 달라지는 지점만 남긴다.)
"""

import json
import re
import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from ..db import get_conn
from ..schemas import CommandRequest, CommandStatusUpdate
from ..services.timeutil import LOCAL_TZ, local_day_range, to_local_iso

router = APIRouter(prefix="/api/control", tags=["control"])

_COOL_PATTERN = re.compile(r"^COOL_(\d+)_(\w+)$")


def action_label(action: Optional[str]) -> str:
    if not action:
        return "알 수 없는 명령"
    if action == "POWER_OFF":
        return "에어컨 끄기"
    if action == "SET_TARGET":
        return "목표 온도 변경"
    matched = _COOL_PATTERN.match(action)
    if matched:
        return f"냉방 {matched.group(1)}°C · {matched.group(2).lower()}"
    return action


@router.get("/logs")
def list_logs(
    room_id: str = Query(...),
    date: Optional[str] = Query(default=None, description="YYYY-MM-DD (로컬 기준)"),
    method: Optional[str] = Query(default=None, pattern="^(rule|manual|predict)$"),
):
    if date:
        try:
            day = datetime.strptime(date, "%Y-%m-%d").date()
        except ValueError:
            raise HTTPException(status_code=400, detail="date 형식은 YYYY-MM-DD 입니다.")
    else:
        day = datetime.now(LOCAL_TZ).date()
    start_utc, end_utc = local_day_range(day)

    with get_conn() as conn:
        entries = []

        # 1) 자동 판단 — 액션이 바뀐 지점만
        auto_rows = conn.execute(
            """
            WITH changes AS (
                SELECT rowid, timestamp, control_mode, proposed_action, executed,
                       occupancy_state, temperature_c, co2_ppm, reason_codes_json,
                       LAG(proposed_action) OVER (ORDER BY timestamp) AS prev_action
                FROM control_decisions
                WHERE room_id = ?
            )
            SELECT * FROM changes
            WHERE (prev_action IS NULL OR prev_action != proposed_action)
                  AND timestamp >= ? AND timestamp < ?
            ORDER BY timestamp DESC
            """,
            (room_id, start_utc, end_utc),
        ).fetchall()

        for row in auto_rows:
            executed = bool(row["executed"])
            shadow = row["control_mode"] == "shadow"
            entries.append(
                {
                    "id": f"decision:{row['rowid']}",
                    "room_id": room_id,
                    "timestamp": to_local_iso(row["timestamp"]),
                    "method": "rule",
                    "content": action_label(row["proposed_action"]),
                    # shadow 모드는 IR를 일부러 쏘지 않는 것이므로 실패가 아니다.
                    "success": executed or shadow,
                    "executed": executed,
                    "simulated": shadow and not executed,
                    "control_mode": row["control_mode"],
                    "occupancy_state": row["occupancy_state"],
                    "temperature": row["temperature_c"],
                    "co2": row["co2_ppm"],
                    "reason_codes": json.loads(row["reason_codes_json"] or "[]"),
                    "failure_title": None,
                    "error_code": None,
                }
            )

        # 2) 사용자 수동 명령
        cmd_rows = conn.execute(
            """
            SELECT * FROM control_commands
            WHERE room_id = ? AND created_at >= ? AND created_at < ?
            ORDER BY created_at DESC
            """,
            (room_id, start_utc, end_utc),
        ).fetchall()

        for row in cmd_rows:
            failed = row["status"] == "failed"
            entries.append(
                {
                    "id": f"command:{row['id']}",
                    "room_id": room_id,
                    "timestamp": to_local_iso(row["created_at"]),
                    "method": row["method"],
                    "content": action_label(row["action"]),
                    "success": row["status"] == "sent",
                    "executed": row["status"] == "sent",
                    "simulated": False,
                    "control_mode": None,
                    "occupancy_state": None,
                    "temperature": None,
                    "co2": None,
                    "reason_codes": [],
                    "failure_title": f"{action_label(row['action'])} 명령이 실패했어요" if failed else None,
                    "error_code": row["error_code"],
                    "status": row["status"],
                    "issued_by": row["issued_by"],
                }
            )

    entries.sort(key=lambda e: e["timestamp"] or "", reverse=True)
    if method:
        entries = [e for e in entries if e["method"] == method]
    return entries


@router.get("/logs/{log_id}")
def get_log(log_id: str, room_id: Optional[str] = Query(default=None)):
    """단건 조회. 목록과 같은 형태를 돌려준다.

    프론트의 상세 화면은 로그 ID만 들고 이동하므로 room_id 없이도 찾을 수 있어야 한다.
    """
    kind, _, raw_id = log_id.partition(":")
    if kind not in {"decision", "command"}:
        raise HTTPException(status_code=400, detail="잘못된 로그 ID 형식입니다.")

    with get_conn() as conn:
        if kind == "decision":
            if room_id:
                row = conn.execute(
                    "SELECT rowid, * FROM control_decisions WHERE rowid = ? AND room_id = ?",
                    (raw_id, room_id),
                ).fetchone()
            else:
                row = conn.execute(
                    "SELECT rowid, * FROM control_decisions WHERE rowid = ?", (raw_id,)
                ).fetchone()
            if row is None:
                raise HTTPException(status_code=404, detail="로그를 찾을 수 없습니다.")
            executed = bool(row["executed"])
            shadow = row["control_mode"] == "shadow"
            return {
                "id": log_id,
                "room_id": row["room_id"],
                "timestamp": to_local_iso(row["timestamp"]),
                "method": "rule",
                "content": action_label(row["proposed_action"]),
                "success": executed or shadow,
                "executed": executed,
                "simulated": shadow and not executed,
                "control_mode": row["control_mode"],
                "occupancy_state": row["occupancy_state"],
                "temperature": row["temperature_c"],
                "co2": row["co2_ppm"],
                "reason_codes": json.loads(row["reason_codes_json"] or "[]"),
                "failure_title": None,
                "error_code": None,
            }

        if room_id:
            row = conn.execute(
                "SELECT * FROM control_commands WHERE id = ? AND room_id = ?", (raw_id, room_id)
            ).fetchone()
        else:
            row = conn.execute(
                "SELECT * FROM control_commands WHERE id = ?", (raw_id,)
            ).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="로그를 찾을 수 없습니다.")
        failed = row["status"] == "failed"
        return {
            "id": log_id,
            "room_id": row["room_id"],
            "timestamp": to_local_iso(row["created_at"]),
            "method": row["method"],
            "content": action_label(row["action"]),
            "success": row["status"] == "sent",
            "executed": row["status"] == "sent",
            "simulated": False,
            "reason_codes": [],
            "failure_title": f"{action_label(row['action'])} 명령이 실패했어요" if failed else None,
            "error_code": row["error_code"],
            "status": row["status"],
            "issued_by": row["issued_by"],
        }


@router.post("/commands", status_code=201)
def create_command(room_id: str = Query(...), req: CommandRequest = ...):
    """사용자 제어 명령을 큐에 넣는다. gateway가 pending을 집어가 실행한다."""
    command_id = uuid.uuid4().hex
    now = datetime.now(timezone.utc).isoformat()
    with get_conn() as conn:
        room = conn.execute("SELECT 1 FROM rooms WHERE id = ?", (room_id,)).fetchone()
        if room is None:
            raise HTTPException(status_code=404, detail="공간을 찾을 수 없습니다.")
        conn.execute(
            """
            INSERT INTO control_commands
                (id, room_id, created_at, issued_by, method, action, payload_json, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, 'pending')
            """,
            (command_id, room_id, now, req.issued_by, req.method, req.action,
             json.dumps(req.payload or {}, ensure_ascii=False)),
        )
    return {"id": command_id, "room_id": room_id, "status": "pending", "created_at": now}


@router.get("/commands")
def list_commands(
    room_id: Optional[str] = Query(default=None),
    status: Optional[str] = Query(default=None, pattern="^(pending|sent|failed)$"),
    limit: int = Query(default=50, ge=1, le=500),
):
    clauses, params = [], []
    if room_id:
        clauses.append("room_id = ?")
        params.append(room_id)
    if status:
        clauses.append("status = ?")
        params.append(status)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    params.append(limit)

    with get_conn() as conn:
        rows = conn.execute(
            f"SELECT * FROM control_commands {where} ORDER BY created_at DESC LIMIT ?", params
        ).fetchall()
        return [dict(row) for row in rows]


@router.patch("/commands/{command_id}")
def update_command(command_id: str, req: CommandStatusUpdate):
    """gateway가 실행 결과를 되돌려 기록한다."""
    resolved_at = datetime.now(timezone.utc).isoformat() if req.status != "pending" else None
    with get_conn() as conn:
        cur = conn.execute(
            "UPDATE control_commands SET status = ?, error_code = ?, resolved_at = ? WHERE id = ?",
            (req.status, req.error_code, resolved_at, command_id),
        )
        if cur.rowcount == 0:
            raise HTTPException(status_code=404, detail="명령을 찾을 수 없습니다.")
        row = conn.execute("SELECT * FROM control_commands WHERE id = ?", (command_id,)).fetchone()
        return dict(row)
