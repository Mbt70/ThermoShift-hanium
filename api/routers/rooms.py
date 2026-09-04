from fastapi import APIRouter, Depends, HTTPException, Query
from typing import Literal

from pydantic import BaseModel, Field

from api.db import get_conn
from api.security import get_current_user_id, require_room_owner
from api.services.power_estimation import calculate_power_snapshot

router = APIRouter(prefix="/rooms", tags=["rooms"])

_LIST_COLUMNS = (
    "room_id, owner_user_id, name, location, control_mode, floor_plan_url, "
    "target_temp, temp_tolerance, co2_limit, humidity_min, humidity_max, updated_at"
)


class CreateRoomRequest(BaseModel):
    # 구버전 클라이언트 호환용. 서버는 이 값을 신뢰하지 않고 인증 사용자를 저장한다.
    owner_user_id: int | None = None
    name: str = Field(min_length=1, max_length=100)
    location: str | None = Field(default=None, max_length=200)
    floor_plan_url: str | None = Field(default=None, max_length=500)


class UpdateRoomRequest(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    location: str | None = Field(default=None, max_length=200)
    floor_plan_url: str | None = Field(default=None, max_length=500)


class UpdateTargetTempRequest(BaseModel):
    target_temp: float = Field(ge=16, le=30)


class UpdateControlModeRequest(BaseModel):
    control_mode: Literal["monitoring", "manual", "rule", "mpc"]


@router.get("")
def list_rooms(owner_user_id: int | None = None,
               current_user_id: int = Depends(get_current_user_id)):
    """GET /rooms?owner_user_id=1

    Response: list of
    [
      {
        "room_id": int,
        "owner_user_id": int,
        "name": str,
        "location": str | null,
        "control_mode": "monitoring" | "manual" | "rule" | "mpc",
        "floor_plan_url": str | null,
        "target_temp": float,
        "temp_tolerance": float,
        "co2_limit": int,
        "humidity_min": float,
        "humidity_max": float,
        "updated_at": str  # ISO 8601 UTC
      },
      ...
    ]
    """
    with get_conn() as conn, conn.cursor() as cur:
        # query parameter는 구버전 클라이언트 호환용이며 접근 범위를 넓히지 않는다.
        cur.execute(
            f"SELECT {_LIST_COLUMNS} FROM rooms WHERE owner_user_id = %s ORDER BY room_id",
            (current_user_id,),
        )
        return cur.fetchall()


@router.get("/{room_id}")
def get_room(room_id: int, current_user_id: int = Depends(get_current_user_id)):
    """GET /rooms/{room_id} - Response: same shape as one list_rooms() entry."""
    require_room_owner(room_id, current_user_id)
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(f"SELECT {_LIST_COLUMNS} FROM rooms WHERE room_id = %s", (room_id,))
        row = cur.fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="room not found")
    return row


@router.post("")
def create_room(body: CreateRoomRequest,
                current_user_id: int = Depends(get_current_user_id)):
    """POST /rooms - Response: same shape as one list_rooms() entry."""
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            f"""
            INSERT INTO rooms (owner_user_id, name, location, floor_plan_url)
            VALUES (%s, %s, %s, %s)
            RETURNING {_LIST_COLUMNS}
            """,
            (current_user_id, body.name, body.location, body.floor_plan_url),
        )
        row = cur.fetchone()
        conn.commit()
    return row


@router.patch("/{room_id}")
def update_room(room_id: int, body: UpdateRoomRequest,
                current_user_id: int = Depends(get_current_user_id)):
    """PATCH /rooms/{room_id} - Response: same shape as one list_rooms() entry."""
    require_room_owner(room_id, current_user_id)
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            f"""
            UPDATE rooms SET name = %s, location = %s,
                   floor_plan_url = COALESCE(%s, floor_plan_url)
            WHERE room_id = %s
            RETURNING {_LIST_COLUMNS}
            """,
            (body.name, body.location, body.floor_plan_url, room_id),
        )
        row = cur.fetchone()
        conn.commit()
    if row is None:
        raise HTTPException(status_code=404, detail="room not found")
    return row


@router.patch("/{room_id}/target-temp")
def update_target_temp(room_id: int, body: UpdateTargetTempRequest,
                       current_user_id: int = Depends(get_current_user_id)):
    """PATCH /rooms/{room_id}/target-temp - Response: same shape as one list_rooms() entry."""
    require_room_owner(room_id, current_user_id)
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            f"UPDATE rooms SET target_temp = %s WHERE room_id = %s RETURNING {_LIST_COLUMNS}",
            (body.target_temp, room_id),
        )
        row = cur.fetchone()
        conn.commit()
    if row is None:
        raise HTTPException(status_code=404, detail="room not found")
    return row


@router.patch("/{room_id}/control-mode")
def update_control_mode(room_id: int, body: UpdateControlModeRequest,
                        current_user_id: int = Depends(get_current_user_id)):
    """PATCH /rooms/{room_id}/control-mode - Response: same shape as one list_rooms() entry."""
    require_room_owner(room_id, current_user_id)
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            f"UPDATE rooms SET control_mode = %s WHERE room_id = %s RETURNING {_LIST_COLUMNS}",
            (body.control_mode, room_id),
        )
        row = cur.fetchone()
        conn.commit()
    if row is None:
        raise HTTPException(status_code=404, detail="room not found")
    return row


@router.delete("/{room_id}")
def delete_room(room_id: int, current_user_id: int = Depends(get_current_user_id)):
    """DELETE /rooms/{room_id} - Response: {"status": "ok"}"""
    require_room_owner(room_id, current_user_id)
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM rooms WHERE room_id = %s RETURNING room_id", (room_id,))
        row = cur.fetchone()
        conn.commit()
    if row is None:
        raise HTTPException(status_code=404, detail="room not found")
    return {"status": "ok"}


@router.get("/{room_id}/latest")
def get_room_latest(room_id: int,
                    current_user_id: int = Depends(get_current_user_id)):
    """GET /rooms/{room_id}/latest

    Response includes env, power, occupancy, door, pir latest telemetry.
    """
    require_room_owner(room_id, current_user_id)
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT
                r.room_id,
                r.target_temp,
                r.temp_tolerance,
                r.co2_limit,
                env.temperature,
                env.humidity,
                env.co2,
                env.measured_at AS env_measured_at,
                pw.power_w,
                pw.measured_at AS power_measured_at,
                occ.occupancy_state,
                occ.estimated_count,
                occ.probability,
                door.door_state,
                door.measured_at AS door_measured_at,
                pir.motion,
                pir.measured_at AS pir_measured_at,
                actuator.cooling_state,
                actuator.measured_at AS actuator_measured_at
            FROM rooms r
            LEFT JOIN LATERAL (
                SELECT se.temperature, se.humidity, se.co2, se.measured_at
                FROM sensor_env se
                JOIN devices d ON d.device_id = se.device_id
                WHERE d.room_id = r.room_id AND d.device_type = 'env'
                ORDER BY se.measured_at DESC
                LIMIT 1
            ) env ON true
            LEFT JOIN LATERAL (
                SELECT pr.power_w, pr.measured_at
                FROM power_readings pr
                JOIN devices d ON d.device_id = pr.device_id
                WHERE d.room_id = r.room_id AND d.device_type = 'plug'
                ORDER BY pr.measured_at DESC
                LIMIT 1
            ) pw ON true
            LEFT JOIN LATERAL (
                SELECT oe.occupancy_state, oe.estimated_count, oe.probability
                FROM occupancy_estimates oe
                WHERE oe.room_id = r.room_id
                ORDER BY oe.estimated_at DESC
                LIMIT 1
            ) occ ON true
            LEFT JOIN LATERAL (
                SELECT sd.door_state, sd.measured_at
                FROM sensor_door sd
                JOIN devices d ON d.device_id = sd.device_id
                WHERE d.room_id = r.room_id AND d.device_type IN ('pir', 'door')
                ORDER BY sd.measured_at DESC
                LIMIT 1
            ) door ON true
            LEFT JOIN LATERAL (
                SELECT sp.motion, sp.measured_at
                FROM sensor_pir sp
                JOIN devices d ON d.device_id = sp.device_id
                WHERE d.room_id = r.room_id AND d.device_type IN ('pir', 'door')
                ORDER BY sp.measured_at DESC
                LIMIT 1
            ) pir ON true
            LEFT JOIN LATERAL (
                SELECT
                    CASE
                        WHEN ie.code_hash = 'COOLING_ON' THEN 'ON'
                        WHEN ie.code_hash = 'COOLING_OFF' THEN 'OFF'
                        ELSE NULL
                    END AS cooling_state,
                    ie.occurred_at AS measured_at
                FROM ir_events ie
                WHERE ie.room_id = r.room_id
                  AND ie.direction = 'rx'
                  AND ie.source = 'device_state_ack'
                  AND ie.code_hash IN ('COOLING_ON', 'COOLING_OFF')
                ORDER BY ie.occurred_at DESC
                LIMIT 1
            ) actuator ON true
            WHERE r.room_id = %s
            """,
            (room_id,),
        )
        row = cur.fetchone()

    if row is None:
        raise HTTPException(status_code=404, detail="room not found")

    power = calculate_power_snapshot(
        measured_power_w=row["power_w"],
        measured_at=row["power_measured_at"],
        cooling_state=row["cooling_state"],
        cooling_state_at=row["actuator_measured_at"],
    )
    return {
        "room_id": row["room_id"],
        "target_temp": row["target_temp"],
        "temp_tolerance": row["temp_tolerance"],
        "co2_limit": row["co2_limit"],
        "env": {
            "temperature": row["temperature"],
            "humidity": row["humidity"],
            "co2": row["co2"],
            "measured_at": row["env_measured_at"],
        },
        "power": power,
        "actuator": {
            "cooling_state": power["cooling_state"],
            "measured_at": power["state_measured_at"],
        },
        "occupancy": {
            "occupancy_state": row["occupancy_state"],
            "estimated_count": row["estimated_count"],
            "probability": row["probability"],
        },
        "door": {
            "door_state": row["door_state"],
            "measured_at": row["door_measured_at"],
        },
        "pir": {
            "motion": row["motion"],
            "measured_at": row["pir_measured_at"],
        },
    }


@router.get("/{room_id}/trend")
def get_room_trend(
    room_id: int,
    minutes: int = Query(default=30, ge=1, le=43_200),
    points: int = Query(default=300, ge=10, le=1_000),
    current_user_id: int = Depends(get_current_user_id),
):
    """GET /rooms/{room_id}/trend?minutes=30

    Response: list of readings from the room's env sensor over the window,
    oldest first, for the 30분 추이 chart:
    [{"measured_at": str, "temperature": float | null, "co2": int | null}, ...]

    Empty list (not 404) if the room has no env device or no readings yet.
    """
    require_room_owner(room_id, current_user_id)
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """
            WITH ordered AS (
                SELECT se.measured_at, se.temperature, se.co2,
                       row_number() OVER (ORDER BY se.measured_at) AS row_no,
                       count(*) OVER () AS total
                FROM sensor_env se
                JOIN devices d ON d.device_id = se.device_id
                WHERE d.room_id = %s AND d.device_type = 'env'
                      AND se.measured_at >= now() - (%s || ' minutes')::interval
            )
            SELECT measured_at, temperature, co2
            FROM ordered
            WHERE total <= %s
               OR mod(row_no - 1, greatest(1, ceil(total::numeric / (%s - 1))::int)) = 0
               OR row_no = total
            ORDER BY measured_at ASC
            """,
            (room_id, minutes, points, points),
        )
        return cur.fetchall()
