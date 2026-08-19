"""알림 API."""

from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, HTTPException, Query

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
):
    with get_conn() as conn:
        # 조회 시점에 규칙을 다시 평가해 최신 상태를 반영한다.
        alerting.evaluate_all(conn)

        clauses, params = [], []
        if room_id:
            clauses.append("a.room_id = ?")
            params.append(room_id)
        if status and status != "all":
            clauses.append("a.status = ?")
            params.append(status)
        if type:
            clauses.append("a.type = ?")
            params.append(type)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        params.append(limit)

        rows = conn.execute(
            f"""
            SELECT a.*, r.name AS room_name
            FROM alerts a
            LEFT JOIN rooms r ON r.id = a.room_id
            {where}
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
def alert_summary(room_id: Optional[str] = Query(default=None)):
    with get_conn() as conn:
        alerting.evaluate_all(conn)
        clause = "AND room_id = ?" if room_id else ""
        params = (room_id,) if room_id else ()
        rows = conn.execute(
            f"SELECT severity, COUNT(*) AS count FROM alerts "
            f"WHERE status = 'active' {clause} GROUP BY severity",
            params,
        ).fetchall()
        counts = {row["severity"]: row["count"] for row in rows}
        return {
            "active": sum(counts.values()),
            "critical": counts.get("critical", 0),
            "warning": counts.get("warning", 0),
        }


@router.post("/{alert_id}/read")
def mark_read(alert_id: str):
    with get_conn() as conn:
        cur = conn.execute(
            "UPDATE alerts SET read_at = ? WHERE id = ? AND read_at IS NULL",
            (datetime.now(timezone.utc).isoformat(), alert_id),
        )
        if cur.rowcount == 0:
            exists = conn.execute("SELECT 1 FROM alerts WHERE id = ?", (alert_id,)).fetchone()
            if exists is None:
                raise HTTPException(status_code=404, detail="알림을 찾을 수 없습니다.")
    return {"id": alert_id, "read": True}
