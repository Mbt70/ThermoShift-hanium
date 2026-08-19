"""예약(스케줄) API."""

import json
import uuid
from datetime import date, datetime, timezone
from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from ..db import get_conn
from ..schemas import ScheduleRequest

router = APIRouter(prefix="/api/schedules", tags=["schedules"])

WEEKDAY_CODES = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]


def _payload(row) -> dict:
    data = dict(row)
    data["repeat_days"] = json.loads(data.pop("repeat_days") or "[]")
    data["precool_enabled"] = bool(data["precool_enabled"])
    data["repeat_enabled"] = bool(data["repeat_enabled"])
    return data


@router.get("")
def list_schedules(
    room_id: str = Query(...),
    today_only: bool = Query(default=False, description="오늘 적용되는 예약만"),
):
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM schedules WHERE room_id = ? ORDER BY start_time", (room_id,)
        ).fetchall()
        schedules = [_payload(row) for row in rows]

    if not today_only:
        return schedules

    today = date.today()
    today_code = WEEKDAY_CODES[today.weekday()]
    return [
        s for s in schedules
        if s["date"] == today.isoformat()
        or (s["repeat_enabled"] and today_code in s["repeat_days"])
    ]


@router.post("", status_code=201)
def create_schedule(req: ScheduleRequest, room_id: str = Query(...)):
    invalid = [d for d in req.repeat_days if d not in WEEKDAY_CODES]
    if invalid:
        raise HTTPException(status_code=400, detail=f"잘못된 요일 코드: {invalid}")

    schedule_id = uuid.uuid4().hex
    with get_conn() as conn:
        room = conn.execute("SELECT 1 FROM rooms WHERE id = ?", (room_id,)).fetchone()
        if room is None:
            raise HTTPException(status_code=404, detail="공간을 찾을 수 없습니다.")
        conn.execute(
            """
            INSERT INTO schedules (id, room_id, title, date, start_time, end_time,
                                   target_temperature, precool_enabled,
                                   precool_minutes_before, repeat_enabled,
                                   repeat_days, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (schedule_id, room_id, req.title, req.date, req.start_time, req.end_time,
             req.target_temperature, int(req.precool_enabled), req.precool_minutes_before,
             int(req.repeat_enabled), json.dumps(req.repeat_days),
             datetime.now(timezone.utc).isoformat()),
        )
        row = conn.execute("SELECT * FROM schedules WHERE id = ?", (schedule_id,)).fetchone()
        return _payload(row)


@router.get("/{schedule_id}")
def get_schedule(schedule_id: str):
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM schedules WHERE id = ?", (schedule_id,)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="예약을 찾을 수 없습니다.")
    return _payload(row)


@router.put("/{schedule_id}")
def update_schedule(schedule_id: str, req: ScheduleRequest):
    with get_conn() as conn:
        exists = conn.execute("SELECT 1 FROM schedules WHERE id = ?", (schedule_id,)).fetchone()
        if exists is None:
            raise HTTPException(status_code=404, detail="예약을 찾을 수 없습니다.")
        conn.execute(
            """
            UPDATE schedules SET title=?, date=?, start_time=?, end_time=?,
                                 target_temperature=?, precool_enabled=?,
                                 precool_minutes_before=?, repeat_enabled=?, repeat_days=?
            WHERE id = ?
            """,
            (req.title, req.date, req.start_time, req.end_time, req.target_temperature,
             int(req.precool_enabled), req.precool_minutes_before,
             int(req.repeat_enabled), json.dumps(req.repeat_days), schedule_id),
        )
        row = conn.execute("SELECT * FROM schedules WHERE id = ?", (schedule_id,)).fetchone()
        return _payload(row)


@router.delete("/{schedule_id}", status_code=204)
def delete_schedule(schedule_id: str):
    with get_conn() as conn:
        conn.execute("DELETE FROM schedules WHERE id = ?", (schedule_id,))
    return None
