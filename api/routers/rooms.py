from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from api.db import get_conn

router = APIRouter(prefix="/rooms", tags=["rooms"])

_LIST_COLUMNS = (
    "room_id, owner_user_id, name, location, control_mode, floor_plan_url, "
    "target_temp, temp_tolerance, co2_limit, humidity_min, humidity_max, updated_at"
)


class CreateRoomRequest(BaseModel):
    owner_user_id: int
    name: str
    location: str | None = None
    floor_plan_url: str | None = None


class UpdateRoomRequest(BaseModel):
    name: str
    location: str | None = None
    floor_plan_url: str | None = None


class UpdateTargetTempRequest(BaseModel):
    target_temp: float


class UpdateControlModeRequest(BaseModel):
    control_mode: str


@router.get("")
def list_rooms(owner_user_id: int | None = None):
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
        if owner_user_id is None:
            cur.execute(f"SELECT {_LIST_COLUMNS} FROM rooms ORDER BY room_id")
        else:
            cur.execute(
                f"SELECT {_LIST_COLUMNS} FROM rooms WHERE owner_user_id = %s ORDER BY room_id",
                (owner_user_id,),
            )
        return cur.fetchall()


@router.get("/{room_id}")
def get_room(room_id: int):
    """GET /rooms/{room_id} - Response: same shape as one list_rooms() entry."""
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(f"SELECT {_LIST_COLUMNS} FROM rooms WHERE room_id = %s", (room_id,))
        row = cur.fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="room not found")
    return row


@router.post("")
def create_room(body: CreateRoomRequest):
    """POST /rooms - Response: same shape as one list_rooms() entry."""
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            f"""
            INSERT INTO rooms (owner_user_id, name, location, floor_plan_url)
            VALUES (%s, %s, %s, %s)
            RETURNING {_LIST_COLUMNS}
            """,
            (body.owner_user_id, body.name, body.location, body.floor_plan_url),
        )
        row = cur.fetchone()
        conn.commit()
    return row


@router.patch("/{room_id}")
def update_room(room_id: int, body: UpdateRoomRequest):
    """PATCH /rooms/{room_id} - Response: same shape as one list_rooms() entry."""
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
def update_target_temp(room_id: int, body: UpdateTargetTempRequest):
    """PATCH /rooms/{room_id}/target-temp - Response: same shape as one list_rooms() entry."""
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
def update_control_mode(room_id: int, body: UpdateControlModeRequest):
    """PATCH /rooms/{room_id}/control-mode - Response: same shape as one list_rooms() entry."""
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
def delete_room(room_id: int):
    """DELETE /rooms/{room_id} - Response: {"status": "ok"}"""
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM rooms WHERE room_id = %s RETURNING room_id", (room_id,))
        row = cur.fetchone()
        conn.commit()
    if row is None:
        raise HTTPException(status_code=404, detail="room not found")
    return {"status": "ok"}


@router.get("/{room_id}/latest")
def get_room_latest(room_id: int):
    """GET /rooms/{room_id}/latest

    Response includes env, power, occupancy, door, pir latest telemetry.
    """
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
                pir.measured_at AS pir_measured_at
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
            WHERE r.room_id = %s
            """,
            (room_id,),
        )
        row = cur.fetchone()

    if row is None:
        raise HTTPException(status_code=404, detail="room not found")

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
        "power": {
            "power_w": row["power_w"],
            "measured_at": row["power_measured_at"],
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
def get_room_trend(room_id: int, minutes: int = 30):
    """GET /rooms/{room_id}/trend?minutes=30

    Response: list of readings from the room's env sensor over the window,
    oldest first, for the 30분 추이 chart:
    [{"measured_at": str, "temperature": float | null, "co2": int | null}, ...]

    Empty list (not 404) if the room has no env device or no readings yet.
    """
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT se.measured_at, se.temperature, se.co2
            FROM sensor_env se
            JOIN devices d ON d.device_id = se.device_id
            WHERE d.room_id = %s AND d.device_type = 'env'
                  AND se.measured_at >= now() - (%s || ' minutes')::interval
            ORDER BY se.measured_at ASC
            """,
            (room_id, minutes),
        )
        return cur.fetchall()
