from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from api.db import get_conn
from api.security import get_current_user_id, require_owned_resource, require_room_owner

router = APIRouter(tags=["devices"])

_COLUMNS = (
    "device_id, room_id, device_code, device_uid, device_type, "
    "install_location, comm_status, is_enabled, last_seen_at"
)


class UpdateEnabledRequest(BaseModel):
    is_enabled: bool


@router.get("/rooms/{room_id}/devices")
def list_devices(room_id: int, current_user_id: int = Depends(get_current_user_id)):
    """GET /rooms/{room_id}/devices

    Response: list of
    [
      {
        "device_id": int,
        "room_id": int,
        "device_code": str,       # e.g. "env_01"
        "device_uid": str,
        "device_type": "env" | "pir" | "door" | "ir" | "plug",
        "install_location": str | null,
        "comm_status": "normal" | "offline" | "error" | "unknown",
        "is_enabled": bool,
        "last_seen_at": str | null
      },
      ...
    ]
    """
    require_room_owner(room_id, current_user_id)
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            f"SELECT {_COLUMNS} FROM devices WHERE room_id = %s ORDER BY device_code",
            (room_id,),
        )
        return cur.fetchall()


@router.patch("/devices/{device_id}/enabled")
def update_enabled(device_id: int, body: UpdateEnabledRequest,
                   current_user_id: int = Depends(get_current_user_id)):
    """PATCH /devices/{device_id}/enabled - Response: same shape as one list_devices() entry."""
    require_owned_resource("devices", "device_id", device_id, current_user_id)
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            f"UPDATE devices SET is_enabled = %s WHERE device_id = %s RETURNING {_COLUMNS}",
            (body.is_enabled, device_id),
        )
        row = cur.fetchone()
        conn.commit()
    if row is None:
        raise HTTPException(status_code=404, detail="device not found")
    return row
