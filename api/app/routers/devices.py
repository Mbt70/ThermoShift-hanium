"""디바이스(ESP32 노드/센서) API."""

from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from ..db import get_conn
from ..schemas import DeviceUpdateRequest
from .rooms import _device_payload

router = APIRouter(prefix="/api/devices", tags=["devices"])


@router.get("")
def list_devices(
    room_id: Optional[str] = Query(default=None),
    unassigned: bool = Query(default=False, description="공간 미배정 디바이스만"),
):
    with get_conn() as conn:
        if unassigned:
            rows = conn.execute(
                "SELECT * FROM devices WHERE room_id IS NULL ORDER BY id"
            ).fetchall()
        elif room_id:
            rows = conn.execute(
                "SELECT * FROM devices WHERE room_id = ? ORDER BY type, id", (room_id,)
            ).fetchall()
        else:
            rows = conn.execute("SELECT * FROM devices ORDER BY room_id, type, id").fetchall()
        return [_device_payload(conn, row) for row in rows]


@router.patch("/{device_id}")
def update_device(device_id: str, req: DeviceUpdateRequest):
    fields = {
        "room_id": req.room_id,
        "name": req.name,
        "type": req.type,
        "location": req.location,
        "enabled": None if req.enabled is None else int(req.enabled),
    }
    # room_id 는 None(미배정)으로 되돌리는 것도 유효한 변경이라
    # 명시적으로 전달된 필드만 골라야 한다.
    provided = req.model_dump(exclude_unset=True)
    updates = {k: v for k, v in fields.items() if k in provided}
    if not updates:
        raise HTTPException(status_code=400, detail="변경할 항목이 없습니다.")

    assignments = ", ".join(f"{k} = ?" for k in updates)
    with get_conn() as conn:
        exists = conn.execute("SELECT 1 FROM devices WHERE id = ?", (device_id,)).fetchone()
        if exists is None:
            raise HTTPException(status_code=404, detail="디바이스를 찾을 수 없습니다.")
        if updates.get("room_id"):
            room = conn.execute(
                "SELECT 1 FROM rooms WHERE id = ?", (updates["room_id"],)
            ).fetchone()
            if room is None:
                raise HTTPException(status_code=400, detail="배정하려는 공간이 없습니다.")
        conn.execute(
            f"UPDATE devices SET {assignments} WHERE id = ?", [*updates.values(), device_id]
        )
        row = conn.execute("SELECT * FROM devices WHERE id = ?", (device_id,)).fetchone()
        return _device_payload(conn, row)
