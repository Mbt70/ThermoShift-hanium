from datetime import date, time

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, model_validator

from api.db import get_conn
from api.security import get_current_user_id, require_owned_resource, require_room_owner

router = APIRouter(tags=["schedules"])

_COLUMNS = (
    "schedule_id, room_id, created_by, title, valid_from, valid_until, "
    "start_time, end_time, repeat_days, target_temp, precooling_min, is_active"
)


class ScheduleRequest(BaseModel):
    title: str | None = Field(default=None, max_length=100)
    valid_from: date
    valid_until: date | None = None
    start_time: time
    end_time: time
    repeat_days: list[int] = Field(default_factory=list)  # 1=Mon..7=Sun
    target_temp: float = Field(ge=16, le=30)
    precooling_min: int = Field(default=0, ge=0, le=180)
    created_by: int | None = None

    @model_validator(mode="after")
    def validate_schedule(self):
        if self.valid_until is not None and self.valid_until < self.valid_from:
            raise ValueError("valid_until must be on or after valid_from")
        if self.start_time == self.end_time:
            raise ValueError("start_time and end_time must differ")
        if len(set(self.repeat_days)) != len(self.repeat_days):
            raise ValueError("repeat_days must not contain duplicates")
        if any(day < 1 or day > 7 for day in self.repeat_days):
            raise ValueError("repeat_days entries must be between 1 and 7")
        return self


@router.get("/rooms/{room_id}/schedules")
def list_schedules(room_id: int, current_user_id: int = Depends(get_current_user_id)):
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
    require_room_owner(room_id, current_user_id)
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            f"SELECT {_COLUMNS} FROM schedules WHERE room_id = %s ORDER BY start_time",
            (room_id,),
        )
        return cur.fetchall()


@router.get("/schedules/{schedule_id}")
def get_schedule(schedule_id: int,
                 current_user_id: int = Depends(get_current_user_id)):
    """GET /schedules/{schedule_id} - Response: same shape as one list_schedules() entry."""
    require_owned_resource("schedules", "schedule_id", schedule_id, current_user_id)
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(f"SELECT {_COLUMNS} FROM schedules WHERE schedule_id = %s", (schedule_id,))
        row = cur.fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="schedule not found")
    return row


@router.post("/rooms/{room_id}/schedules")
def create_schedule(room_id: int, body: ScheduleRequest,
                    current_user_id: int = Depends(get_current_user_id)):
    """POST /rooms/{room_id}/schedules - Response: same shape as one list_schedules() entry."""
    require_room_owner(room_id, current_user_id)
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            f"""
            INSERT INTO schedules (room_id, created_by, title, valid_from, valid_until,
                                    start_time, end_time, repeat_days, target_temp, precooling_min)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING {_COLUMNS}
            """,
            (
                room_id, current_user_id, body.title, body.valid_from, body.valid_until,
                body.start_time, body.end_time, body.repeat_days, body.target_temp,
                body.precooling_min,
            ),
        )
        row = cur.fetchone()
        conn.commit()
    return row


@router.patch("/schedules/{schedule_id}")
def update_schedule(schedule_id: int, body: ScheduleRequest,
                    current_user_id: int = Depends(get_current_user_id)):
    """PATCH /schedules/{schedule_id} - Response: same shape as one list_schedules() entry."""
    require_owned_resource("schedules", "schedule_id", schedule_id, current_user_id)
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
def delete_schedule(schedule_id: int,
                    current_user_id: int = Depends(get_current_user_id)):
    """DELETE /schedules/{schedule_id} - Response: {"status": "ok"}"""
    require_owned_resource("schedules", "schedule_id", schedule_id, current_user_id)
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            "DELETE FROM schedules WHERE schedule_id = %s RETURNING schedule_id", (schedule_id,)
        )
        row = cur.fetchone()
        conn.commit()
    if row is None:
        raise HTTPException(status_code=404, detail="schedule not found")
    return {"status": "ok"}
