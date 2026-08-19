from datetime import date

from fastapi import APIRouter, HTTPException

from api.db import get_conn

router = APIRouter(tags=["control"])

_COLUMNS = (
    "command_id, room_id, device_id, decision_id, schedule_id, issued_by, "
    "command_type, control_mode, target_temp, command_status, issued_at, "
    "power_before_w, power_after_w, verify_result, result_message, "
    "estimated_cause, action_guide, verified_at"
)


@router.get("/rooms/{room_id}/commands")
def list_commands(room_id: int, day: date | None = None):
    """GET /rooms/{room_id}/commands?day=2026-08-19

    Response: list of HVAC command/control-log entries for the room, newest
    last (issued_at ASC). If `day` is omitted, returns every command for the
    room.
    [
      {
        "command_id": int, "room_id": int, "device_id": int,
        "decision_id": int | null, "schedule_id": int | null,
        "issued_by": int | null,
        "command_type": "power_on" | "power_off" | "set_temp" | "set_mode" | "set_fan",
        "control_mode": "monitoring" | "manual" | "rule" | "mpc",
        "target_temp": float | null,
        "command_status": "pending" | "sent" | "acked" | "failed" | "timeout",
        "issued_at": str,
        "power_before_w": float | null, "power_after_w": float | null,
        "verify_result": "success" | "failed" | "uncertain" | null,
        "result_message": str | null, "estimated_cause": str | null,
        "action_guide": str | null, "verified_at": str | null
      },
      ...
    ]
    """
    with get_conn() as conn, conn.cursor() as cur:
        if day is None:
            cur.execute(
                f"SELECT {_COLUMNS} FROM hvac_commands WHERE room_id = %s ORDER BY issued_at",
                (room_id,),
            )
        else:
            cur.execute(
                f"""
                SELECT {_COLUMNS} FROM hvac_commands
                WHERE room_id = %s AND issued_at::date = %s
                ORDER BY issued_at
                """,
                (room_id, day),
            )
        return cur.fetchall()


@router.get("/commands/{command_id}")
def get_command(command_id: int):
    """GET /commands/{command_id} - Response: same shape as one list_commands() entry."""
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(f"SELECT {_COLUMNS} FROM hvac_commands WHERE command_id = %s", (command_id,))
        row = cur.fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="command not found")
    return row
