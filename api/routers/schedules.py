from datetime import date, time

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from api.db import get_conn

router = APIRouter(tags=["schedules"])

_COLUMNS = (
    "schedule_id, room_id, created_by, title, valid_from, valid_until, "
    "start_time, end_time, repeat_days, target_temp, precooling_min, is_active"
)


class ScheduleRequest(BaseModel):
    title: str | None = None
    valid_from: date
    valid_until: date | None = None
    start_time: time
    end_time: time
    repeat_days: list[int] = []  # 1=Mon..7=Sun, matching ISO weekday
    target_temp: float
    precooling_min: int = 0
    created_by: int | None = None


@router.get("/rooms/{room_id}/schedules")
def list_schedules(room_id: int):
    """GET /rooms/{room_id}/schedules

    Response: list of
    [
      {
        "schedule_id": int, "room_id": int, "created_by": int | null,
        "title": str | null, "valid_from": str, "valid_until": str | null,
        "start_time": str, "end_time": str, "repeat_days": [int, ...],
        "target_temp": float, "precooling_min": int, "is_active": bool
      },
      ...
    ]
    """
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            f"SELECT {_COLUMNS} FROM schedules WHERE room_id = %s ORDER BY start_time",
            (room_id,),
        )
        return cur.fetchall()


@router.get("/schedules/{schedule_id}")
def get_schedule(schedule_id: int):
    """GET /schedules/{schedule_id} - Response: same shape as one list_schedules() entry."""
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(f"SELECT {_COLUMNS} FROM schedules WHERE schedule_id = %s", (schedule_id,))
        row = cur.fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="schedule not found")
    return row


@router.post("/rooms/{room_id}/schedules")
def create_schedule(room_id: int, body: ScheduleRequest):
    """POST /rooms/{room_id}/schedules - Response: same shape as one list_schedules() entry."""
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            f"""
            INSERT INTO schedules (room_id, created_by, title, valid_from, valid_until,
                                    start_time, end_time, repeat_days, target_temp, precooling_min)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING {_COLUMNS}
            """,
            (
                room_id, body.created_by, body.title, body.valid_from, body.valid_until,
                body.start_time, body.end_time, body.repeat_days, body.target_temp,
                body.precooling_min,
            ),
        )
        row = cur.fetchone()
        conn.commit()
    return row


@router.patch("/schedules/{schedule_id}")
def update_schedule(schedule_id: int, body: ScheduleRequest):
    """PATCH /schedules/{schedule_id} - Response: same shape as one list_schedules() entry."""
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            f"""
            UPDATE schedules SET title = %s, valid_from = %s, valid_until = %s,
                   start_time = %s, end_time = %s, repeat_days = %s,
                   target_temp = %s, precooling_min = %s
            WHERE schedule_id = %s
            RETURNING {_COLUMNS}
            """,
            (
                body.title, body.valid_from, body.valid_until, body.start_time, body.end_time,
                body.repeat_days, body.target_temp, body.precooling_min, schedule_id,
            ),
        )
        row = cur.fetchone()
        conn.commit()
    if row is None:
        raise HTTPException(status_code=404, detail="schedule not found")
    return row


@router.delete("/schedules/{schedule_id}")
def delete_schedule(schedule_id: int):
    """DELETE /schedules/{schedule_id} - Response: {"status": "ok"}"""
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            "DELETE FROM schedules WHERE schedule_id = %s RETURNING schedule_id", (schedule_id,)
        )
        row = cur.fetchone()
        conn.commit()
    if row is None:
        raise HTTPException(status_code=404, detail="schedule not found")
    return {"status": "ok"}
