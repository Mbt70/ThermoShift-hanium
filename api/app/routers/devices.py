"""디바이스(ESP32 노드/센서) API."""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from ..auth import current_user, require_room_access
from ..db import get_conn
from ..schemas import DeviceUpdateRequest
from .rooms import _device_payload

router = APIRouter(prefix="/api/devices", tags=["devices"])


@router.get("")
def list_devices(
    room_id: Optional[str] = Query(default=None),
    unassigned: bool = Query(default=False, description="공간 미배정 디바이스만"),
    actor: str = Depends(current_user),
):
    if room_id:
        require_room_access(room_id, actor)
    with get_conn() as conn:
        if unassigned:
            # 미배정 디바이스는 아직 주인이 없다. 등록하려면 봐야 하므로 공개한다.
            rows = conn.execute(
                "SELECT * FROM devices WHERE room_id IS NULL ORDER BY id"
            ).fetchall()
        elif room_id:
            rows = conn.execute(
                "SELECT * FROM devices WHERE room_id = ? ORDER BY type, id", (room_id,)
            ).fetchall()
        else:
            # 소유한 공간의 디바이스 + 미배정 디바이스만 보인다.
            rows = conn.execute(
                """
                SELECT d.* FROM devices d
                LEFT JOIN rooms r ON r.id = d.room_id
                WHERE d.room_id IS NULL OR r.owner_email = ?
                ORDER BY d.room_id, d.type, d.id
                """,
                (actor,),
            ).fetchall()
        return [_device_payload(conn, row) for row in rows]


@router.patch("/{device_id}")
def update_device(device_id: str, req: DeviceUpdateRequest, actor: str = Depends(current_user)):
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
        existing = conn.execute(
            "SELECT room_id FROM devices WHERE id = ?", (device_id,)
        ).fetchone()
        if existing is None:
            raise HTTPException(status_code=404, detail="디바이스를 찾을 수 없습니다.")

    # 이미 남의 공간에 배정된 디바이스는 건드릴 수 없다.
    if existing["room_id"]:
        require_room_access(existing["room_id"], actor)
    # 옮겨 갈 공간도 본인 것이어야 한다.
    if updates.get("room_id"):
        require_room_access(updates["room_id"], actor)

    with get_conn() as conn:
        conn.execute(
            f"UPDATE devices SET {assignments} WHERE id = ?", [*updates.values(), device_id]
        )
        row = conn.execute("SELECT * FROM devices WHERE id = ?", (device_id,)).fetchone()
        return _device_payload(conn, row)
