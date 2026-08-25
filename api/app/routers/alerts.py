"""알림 API."""

from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from ..auth import current_user, require_room_access
from ..db import get_conn
from ..services import alerting
from ..services.timeutil import to_local_iso

router = APIRouter(prefix="/api/alerts", tags=["alerts"])


@router.get("")
def list_alerts(
    room_id: Optional[str] = Query(default=None),
    status: Optional[str] = Query(default="active", pattern="^(active|resolved|all)$"),
    type: Optional[str] = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    actor: str = Depends(current_user),
):
    if room_id:
        require_room_access(room_id, actor)
    with get_conn() as conn:
        # 조회 시점에 규칙을 다시 평가해 최신 상태를 반영한다.
        alerting.evaluate_all(conn)

        # 소유한 공간의 알림만 보인다.
        clauses, params = ["r.owner_email = ?"], [actor]
        if room_id:
            clauses.append("a.room_id = ?")
            params.append(room_id)
        if status and status != "all":
            clauses.append("a.status = ?")
            params.append(status)
        if type:
            clauses.append("a.type = ?")
            params.append(type)
        params.append(limit)

        rows = conn.execute(
            f"""
            SELECT a.*, r.name AS room_name
            FROM alerts a
            JOIN rooms r ON r.id = a.room_id
            WHERE {' AND '.join(clauses)}
            ORDER BY a.created_at DESC
            LIMIT ?
            """,
            params,
        ).fetchall()

        return [
            {
                **dict(row),
                # 제어 로그와 같은 규칙으로 로컬 시간대 ISO를 내보낸다.
                "created_at": to_local_iso(row["created_at"]),
                "read_at": to_local_iso(row["read_at"]),
                "read": row["read_at"] is not None,
                "room": row["room_name"],
            }
            for row in rows
        ]


@router.get("/summary")
def alert_summary(
    room_id: Optional[str] = Query(default=None),
    actor: str = Depends(current_user),
):
    if room_id:
        require_room_access(room_id, actor)
    with get_conn() as conn:
        alerting.evaluate_all(conn)
        clause = "AND a.room_id = ?" if room_id else ""
        params = (actor, room_id) if room_id else (actor,)
        rows = conn.execute(
            f"""
            SELECT a.severity, COUNT(*) AS count FROM alerts a
            JOIN rooms r ON r.id = a.room_id
            WHERE a.status = 'active' AND r.owner_email = ? {clause}
            GROUP BY a.severity
            """,
            params,
        ).fetchall()
        counts = {row["severity"]: row["count"] for row in rows}
        return {
            "active": sum(counts.values()),
            "critical": counts.get("critical", 0),
            "warning": counts.get("warning", 0),
        }


@router.post("/{alert_id}/read")
def mark_read(alert_id: str, actor: str = Depends(current_user)):
    with get_conn() as conn:
        row = conn.execute("SELECT room_id FROM alerts WHERE id = ?", (alert_id,)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="알림을 찾을 수 없습니다.")
    require_room_access(row["room_id"], actor)

    # 이미 읽음 상태면 아무것도 바뀌지 않는다 (존재 여부는 위에서 확인했다).
    with get_conn() as conn:
        conn.execute(
            "UPDATE alerts SET read_at = ? WHERE id = ? AND read_at IS NULL",
            (datetime.now(timezone.utc).isoformat(), alert_id),
        )
    return {"id": alert_id, "read": True}
