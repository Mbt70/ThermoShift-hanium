"""공간의 현재 상태 스냅샷 조합.

gateway가 남긴 원본 로그(sensor_readings / occupancy_estimates /
control_decisions)를 프론트가 기대하는 하나의 room dict 형태로 합친다.
프론트 room_store가 목데이터로 만들어 쓰던 키를 그대로 채운다.
"""

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

# 이 시간 동안 새 측정값이 없으면 센서가 끊긴 것으로 본다.
# gateway config의 env_data_stale_sec(120) 보다 약간 여유를 둔다.
SENSOR_STALE_SEC = 180

ENV_METRICS = ("temperature", "humidity", "co2")


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _parse_ts(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    # gateway는 UTC aware로 쓰지만, 과거 데이터에 naive가 섞여 있을 수 있다.
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def latest_metric(
    conn: sqlite3.Connection, room_id: str, metric: str
) -> tuple[Optional[float], Optional[str]]:
    """공간에 배정된 디바이스들 중 가장 최근 측정값 하나."""
    row = conn.execute(
        """
        SELECT r.value, r.timestamp
        FROM sensor_readings r
        JOIN devices d ON d.id = r.device_id
        WHERE d.room_id = ? AND r.metric = ? AND r.value IS NOT NULL
              AND (r.quality IS NULL OR r.quality != 'INVALID')
        ORDER BY r.timestamp DESC
        LIMIT 1
        """,
        (room_id, metric),
    ).fetchone()
    if row is None:
        return None, None
    return row["value"], row["timestamp"]


def latest_occupancy(conn: sqlite3.Connection, room_id: str) -> Optional[dict]:
    row = conn.execute(
        """
        SELECT timestamp, p_empty, p_transition, p_occupied, state, quality, reasons_json
        FROM occupancy_estimates
        WHERE room_id = ?
        ORDER BY timestamp DESC
        LIMIT 1
        """,
        (room_id,),
    ).fetchone()
    if row is None:
        return None
    data = dict(row)
    data["reasons"] = json.loads(data.pop("reasons_json") or "[]")
    return data


def latest_decision(conn: sqlite3.Connection, room_id: str) -> Optional[dict]:
    row = conn.execute(
        """
        SELECT timestamp, control_mode, proposed_action, executed,
               occupancy_state, temperature_c, co2_ppm, reason_codes_json
        FROM control_decisions
        WHERE room_id = ?
        ORDER BY timestamp DESC
        LIMIT 1
        """,
        (room_id,),
    ).fetchone()
    if row is None:
        return None
    data = dict(row)
    data["reason_codes"] = json.loads(data.pop("reason_codes_json") or "[]")
    return data


def sensor_connected(conn: sqlite3.Connection, room_id: str) -> bool:
    """환경 센서가 살아 있는지. 최근 측정 시각 기준으로 판단한다."""
    row = conn.execute(
        """
        SELECT MAX(r.timestamp) AS last_ts
        FROM sensor_readings r
        JOIN devices d ON d.id = r.device_id
        WHERE d.room_id = ? AND d.enabled = 1 AND r.metric IN (?, ?, ?)
        """,
        (room_id, *ENV_METRICS),
    ).fetchone()
    last = _parse_ts(row["last_ts"] if row else None)
    if last is None:
        return False
    return (_utcnow() - last).total_seconds() <= SENSOR_STALE_SEC


def estimate_power_kw(aircon_on: bool) -> float:
    """전력 추정치.

    스마트 플러그(plug 타입 디바이스)가 아직 붙지 않아 실측이 없다.
    실측이 들어오면 이 함수 대신 plug 디바이스의 power metric을 쓴다.
    """
    return 1.8 if aircon_on else 0.15


def build_room_payload(conn: sqlite3.Connection, room: sqlite3.Row | dict) -> dict:
    """rooms 테이블 한 행 + 실시간 측정값 → 프론트 room dict."""
    room = dict(room)
    room_id = room["id"]

    temperature, temp_ts = latest_metric(conn, room_id, "temperature")
    humidity, _ = latest_metric(conn, room_id, "humidity")
    co2, co2_ts = latest_metric(conn, room_id, "co2")

    occupancy = latest_occupancy(conn, room_id)
    decision = latest_decision(conn, room_id)

    if occupancy is not None:
        occupied = occupancy["state"] == "OCCUPIED"
    else:
        # HMM 추정이 아직 없으면 PIR 원본으로 대체 판단한다.
        pir_value, _ = latest_metric(conn, room_id, "pir")
        occupied = bool(pir_value)

    aircon_on = bool(decision and decision["proposed_action"] != "POWER_OFF")

    reservation_count = conn.execute(
        "SELECT COUNT(*) FROM schedules WHERE room_id = ?", (room_id,)
    ).fetchone()[0]

    last_updated = max(filter(None, [temp_ts, co2_ts]), default=room.get("updated_at"))

    return {
        "id": room_id,
        "name": room["name"],
        "location": room["location"],
        "floor_plan_name": room["floor_plan_name"],
        "owner_email": room["owner_email"],
        "target_temperature": room["target_temperature"],
        "control_mode": room["control_mode"],
        "auto_control": bool(room["auto_control"]),
        "temperature": temperature,
        "humidity": humidity,
        "co2": co2,
        "occupied": occupied,
        "aircon_on": aircon_on,
        "sensor_connected": sensor_connected(conn, room_id),
        "power": estimate_power_kw(aircon_on),
        "reservation_count": reservation_count,
        "last_updated": last_updated,
        "occupancy": occupancy,
        "decision": decision,
    }


def trend_series(
    conn: sqlite3.Connection,
    room_id: str,
    metric: str,
    hours: int = 3,
    points: int = 30,
) -> list[dict]:
    """최근 N시간을 points개 구간으로 나눈 평균 시계열.

    프론트 차트가 고정 개수의 점을 기대하므로 원본을 그대로 주지 않고
    시간 버킷 평균으로 다운샘플링한다.
    """
    if points < 1:
        return []

    now = _utcnow()
    start = now - timedelta(hours=hours)
    bucket_sec = max(1, int((now - start).total_seconds() / points))

    rows = conn.execute(
        """
        SELECT r.timestamp, r.value
        FROM sensor_readings r
        JOIN devices d ON d.id = r.device_id
        WHERE d.room_id = ? AND r.metric = ? AND r.value IS NOT NULL
              AND (r.quality IS NULL OR r.quality != 'INVALID')
              AND r.timestamp >= ?
        ORDER BY r.timestamp
        """,
        (room_id, metric, start.isoformat()),
    ).fetchall()

    buckets: dict[int, list[float]] = {}
    for row in rows:
        ts = _parse_ts(row["timestamp"])
        if ts is None:
            continue
        index = int((ts - start).total_seconds() // bucket_sec)
        index = min(index, points - 1)
        buckets.setdefault(index, []).append(row["value"])

    series = []
    for index in range(points):
        values = buckets.get(index)
        series.append(
            {
                "timestamp": (start + timedelta(seconds=bucket_sec * index)).isoformat(),
                "value": round(sum(values) / len(values), 2) if values else None,
            }
        )
    return series
