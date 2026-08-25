"""공간(room) API.

응답은 rooms 테이블의 설정값과 gateway가 남긴 실시간 측정값을 합쳐
프론트 room_store가 쓰던 dict 형태 그대로 돌려준다.
"""

import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from ..auth import current_user, require_room_access
from ..db import get_conn
from ..schemas import RoomCreateRequest, RoomUpdateRequest
from ..services import snapshot

router = APIRouter(prefix="/api/rooms", tags=["rooms"])


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _fetch_room(conn, room_id: str):
    row = conn.execute("SELECT * FROM rooms WHERE id = ?", (room_id,)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="공간을 찾을 수 없습니다.")
    return row


@router.get("")
def list_rooms(
    owner_email: Optional[str] = Query(default=None),
    actor: str = Depends(current_user),
):
    # owner_email 파라미터는 하위 호환으로 받되, 실제로는 항상 본인 소유만 돌려준다.
    # 남의 공간 목록을 조회할 수 있으면 안 된다.
    del owner_email
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM rooms WHERE owner_email = ? ORDER BY created_at", (actor,)
        ).fetchall()
        return [snapshot.build_room_payload(conn, row) for row in rows]


@router.post("", status_code=201)
def create_room(req: RoomCreateRequest, actor: str = Depends(current_user)):
    room_id = uuid.uuid4().hex
    now = _now()
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO rooms (id, name, location, floor_plan_name, owner_email,
                               target_temperature, control_mode, auto_control,
                               created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, 24.0, 'rule', 1, ?, ?)
            """,
            # 요청 본문의 owner_email 은 무시하고 토큰의 사용자를 소유자로 박는다.
            (room_id, req.name, req.location, req.floor_plan_name, actor, now, now),
        )
        return snapshot.build_room_payload(conn, _fetch_room(conn, room_id))


@router.get("/{room_id}")
def get_room(room_id: str, actor: str = Depends(current_user)):
    require_room_access(room_id, actor)
    with get_conn() as conn:
        return snapshot.build_room_payload(conn, _fetch_room(conn, room_id))


@router.patch("/{room_id}")
def update_room(room_id: str, req: RoomUpdateRequest, actor: str = Depends(current_user)):
    require_room_access(room_id, actor)
    fields = {
        "name": req.name,
        "location": req.location,
        "floor_plan_name": req.floor_plan_name,
        "target_temperature": req.target_temperature,
        "control_mode": req.control_mode,
        "auto_control": None if req.auto_control is None else int(req.auto_control),
    }
    updates = {k: v for k, v in fields.items() if v is not None}
    if not updates:
        raise HTTPException(status_code=400, detail="변경할 항목이 없습니다.")

    assignments = ", ".join(f"{k} = ?" for k in updates)
    params = [*updates.values(), _now(), room_id]
    with get_conn() as conn:
        _fetch_room(conn, room_id)
        conn.execute(f"UPDATE rooms SET {assignments}, updated_at = ? WHERE id = ?", params)
        return snapshot.build_room_payload(conn, _fetch_room(conn, room_id))


@router.delete("/{room_id}", status_code=204)
def delete_room(room_id: str, actor: str = Depends(current_user)):
    require_room_access(room_id, actor)
    with get_conn() as conn:
        conn.execute("DELETE FROM rooms WHERE id = ?", (room_id,))
    return None


@router.get("/{room_id}/trend")
def get_trend(
    room_id: str,
    metric: str = Query(default="temperature"),
    hours: int = Query(default=3, ge=1, le=8760),
    points: int = Query(default=30, ge=2, le=500),
    actor: str = Depends(current_user),
):
    require_room_access(room_id, actor)
    allowed = {"temperature", "humidity", "co2", "pir", "door", "power"}
    if metric not in allowed:
        raise HTTPException(status_code=400, detail=f"지원하지 않는 metric: {metric}")
    with get_conn() as conn:
        _fetch_room(conn, room_id)
        return {
            "room_id": room_id,
            "metric": metric,
            "hours": hours,
            "series": snapshot.trend_series(conn, room_id, metric, hours, points),
        }


@router.get("/{room_id}/devices")
def list_room_devices(room_id: str, actor: str = Depends(current_user)):
    require_room_access(room_id, actor)
    with get_conn() as conn:
        _fetch_room(conn, room_id)
        rows = conn.execute(
            "SELECT * FROM devices WHERE room_id = ? ORDER BY type, id", (room_id,)
        ).fetchall()
        return [_device_payload(conn, row) for row in rows]


def _device_payload(conn, row) -> dict:
    """디바이스 행 + 마지막 수신 시각으로 연결 상태를 붙인다."""
    device = dict(row)
    last_row = conn.execute(
        "SELECT MAX(timestamp) AS last_ts FROM sensor_readings WHERE device_id = ?",
        (device["id"],),
    ).fetchone()
    last_ts = last_row["last_ts"] if last_row else None
    device["last_seen"] = last_ts or device.get("last_seen")
    device["enabled"] = bool(device["enabled"])

    parsed = snapshot._parse_ts(device["last_seen"])
    if parsed is None:
        device["status"] = None
    elif (snapshot._utcnow() - parsed).total_seconds() <= snapshot.SENSOR_STALE_SEC:
        device["status"] = "success"
    else:
        device["status"] = "disconnected"
    return device
