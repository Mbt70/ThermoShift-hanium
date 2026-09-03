from datetime import date

from fastapi import APIRouter, Depends, HTTPException

from api.db import get_conn
from api.security import get_current_user_id, require_owned_resource, require_room_owner

router = APIRouter(tags=["events"])

_COLUMNS = (
    "event_id, room_id, device_id, command_id, event_category, event_severity, "
    "status, message, occurred_at, read_at, resolved_at"
)


@router.get("/rooms/{room_id}/events")
def list_events(room_id: int, day: date | None = None,
                current_user_id: int = Depends(get_current_user_id)):
    """GET /rooms/{room_id}/events?day=2026-08-19

    Response: list of alert/event entries for the room, oldest first. If
    `day` is omitted, returns every event for the room.
    [
      {
        "event_id": int, "room_id": int, "device_id": int | null,
        "command_id": int | null,
        "event_category": "sensor_error" | "co2_exceed" | "temp_deviation" |
                           "control_fail" | "network" | "schedule" | "energy" | "system",
        "event_severity": "info" | "warning" | "critical",
        "status": "open" | "read" | "resolved",
        "message": str | null, "occurred_at": str,
        "read_at": str | null, "resolved_at": str | null
      },
      ...
    ]
    """
    require_room_owner(room_id, current_user_id)
    with get_conn() as conn, conn.cursor() as cur:
        if day is None:
            cur.execute(
                f"SELECT {_COLUMNS} FROM event_logs WHERE room_id = %s ORDER BY occurred_at",
                (room_id,),
            )
        else:
            cur.execute(
                f"""
                SELECT {_COLUMNS} FROM event_logs
                WHERE room_id = %s AND occurred_at::date = %s
                ORDER BY occurred_at
                """,
                (room_id, day),
            )
        return cur.fetchall()


@router.get("/events/{event_id}")
def get_event(event_id: int,
              current_user_id: int = Depends(get_current_user_id)):
    """GET /events/{event_id} - Response: same shape as one list_events() entry."""
    require_owned_resource("event_logs", "event_id", event_id, current_user_id)
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(f"SELECT {_COLUMNS} FROM event_logs WHERE event_id = %s", (event_id,))
        row = cur.fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="event not found")
    return row


@router.patch("/events/{event_id}/read")
def mark_read(event_id: int,
              current_user_id: int = Depends(get_current_user_id)):
    """PATCH /events/{event_id}/read - marks the event read (open -> read only;
    already-read/resolved events are left as-is). Response: same shape as one
    list_events() entry.
    """
    require_owned_resource("event_logs", "event_id", event_id, current_user_id)
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            f"""
            UPDATE event_logs SET status = 'read', read_at = now()
            WHERE event_id = %s AND status = 'open'
            RETURNING {_COLUMNS}
            """,
            (event_id,),
        )
        row = cur.fetchone()
        if row is None:
            cur.execute(f"SELECT {_COLUMNS} FROM event_logs WHERE event_id = %s", (event_id,))
            row = cur.fetchone()
        conn.commit()
    if row is None:
        raise HTTPException(status_code=404, detail="event not found")
    return row
