"""알림 규칙 평가.

현재 상태를 규칙에 넣어 alerts 테이블을 최신으로 맞춘다.
같은 원인의 알림이 중복 생성되지 않도록 (공간·유형·디바이스) 조합으로
결정적(deterministic) ID를 만들고, 조건이 풀리면 resolved 로 내린다.
"""

import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Optional

from . import snapshot

# 규칙 임계값. gateway config와 맞춰 둔다.
CO2_WARNING_PPM = 1200
CO2_CRITICAL_PPM = 1500
TEMPERATURE_DEVIATION_C = 3.0
NETWORK_SILENCE_SEC = 300

ALERT_SEVERITY = {
    "sensor_offline": "critical",
    "co2_high": "warning",
    "temperature_abnormal": "warning",
    "control_failed": "critical",
    "network_error": "critical",
    "humidity_abnormal": "warning",
    "door_open": "warning",
    "power_abnormal": "critical",
}


def _alert_id(room_id: str, alert_type: str, device_id: Optional[str]) -> str:
    return f"{room_id}:{alert_type}:{device_id or '-'}"


def _upsert(conn: sqlite3.Connection, room_id: str, alert_type: str,
            device_id: Optional[str], title: str, message: str) -> None:
    alert_id = _alert_id(room_id, alert_type, device_id)
    now = datetime.now(timezone.utc).isoformat()
    existing = conn.execute(
        "SELECT status FROM alerts WHERE id = ?", (alert_id,)
    ).fetchone()

    if existing is None:
        conn.execute(
            """
            INSERT INTO alerts (id, room_id, device_id, type, severity, title, message,
                                created_at, status, read_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'active', NULL)
            """,
            (alert_id, room_id, device_id, alert_type,
             ALERT_SEVERITY.get(alert_type, "warning"), title, message, now),
        )
    elif existing["status"] == "resolved":
        # 다시 발생한 경우: 새 발생 시각으로 되살리고 읽음 표시를 지운다.
        conn.execute(
            "UPDATE alerts SET status='active', created_at=?, read_at=NULL, message=? WHERE id=?",
            (now, message, alert_id),
        )
    else:
        conn.execute("UPDATE alerts SET message = ? WHERE id = ?", (message, alert_id))


def _resolve(conn: sqlite3.Connection, room_id: str, alert_type: str,
             device_id: Optional[str]) -> None:
    conn.execute(
        "UPDATE alerts SET status = 'resolved' WHERE id = ? AND status = 'active'",
        (_alert_id(room_id, alert_type, device_id),),
    )


def evaluate_room(conn: sqlite3.Connection, room: sqlite3.Row | dict) -> None:
    room = dict(room)
    room_id = room["id"]
    now = snapshot._utcnow()

    # --- 규칙 1: 센서 노드 오프라인 ---
    devices = conn.execute(
        "SELECT id, type FROM devices WHERE room_id = ? AND enabled = 1", (room_id,)
    ).fetchall()
    latest_any: Optional[datetime] = None

    for device in devices:
        row = conn.execute(
            "SELECT MAX(timestamp) AS last_ts FROM sensor_readings WHERE device_id = ?",
            (device["id"],),
        ).fetchone()
        last = snapshot._parse_ts(row["last_ts"] if row else None)
        if last and (latest_any is None or last > latest_any):
            latest_any = last

        # IR 송신기처럼 측정값을 올리지 않는 장비는 오프라인 판정에서 제외한다.
        if device["type"] not in ("env", "pir", "door", "plug"):
            continue

        offline = last is None or (now - last).total_seconds() > snapshot.SENSOR_STALE_SEC
        if offline:
            _upsert(conn, room_id, "sensor_offline", device["id"],
                    "센서 노드 오프라인",
                    f"{device['id']} 신호 없음 → 제어 판단 불가")
        else:
            _resolve(conn, room_id, "sensor_offline", device["id"])

    # --- 규칙 2: 네트워크 (공간 전체가 조용함) ---
    if devices:
        silent = latest_any is None or (now - latest_any).total_seconds() > NETWORK_SILENCE_SEC
        if silent:
            _upsert(conn, room_id, "network_error", None,
                    "네트워크 연결 오류",
                    "장비와 서버 간 통신이 5분 이상 원활하지 않습니다. "
                    "게이트웨이 전원과 공유기 연결 상태를 확인해 주세요.")
        else:
            _resolve(conn, room_id, "network_error", None)

    # --- 규칙 3: 제어 명령 실패 ---
    recent = (now - timedelta(hours=1)).isoformat()
    failed = conn.execute(
        "SELECT COUNT(*) FROM control_commands "
        "WHERE room_id = ? AND status = 'failed' AND created_at >= ?",
        (room_id, recent),
    ).fetchone()[0]
    if failed:
        _upsert(conn, room_id, "control_failed", None,
                f"IR 명령 {failed}회 실패",
                "에어컨 응답 없음 → 수동 제어가 필요합니다.")
    else:
        _resolve(conn, room_id, "control_failed", None)

    # 센서가 끊긴 상태에서는 아래 환경 규칙(CO2·온도)의 값이 낡은 값이므로 평가하지 않는다.
    if not snapshot.sensor_connected(conn, room_id):
        return

    # --- 규칙 4: CO2 초과 ---
    co2, _ = snapshot.latest_metric(conn, room_id, "co2")
    if co2 is not None and co2 >= CO2_WARNING_PPM:
        level = "심각" if co2 >= CO2_CRITICAL_PPM else "주의"
        _upsert(conn, room_id, "co2_high", None,
                "CO₂ 농도 기준 초과",
                f"CO₂ 농도가 {co2:.0f}ppm 입니다({level}). 환기가 필요합니다.")
    else:
        _resolve(conn, room_id, "co2_high", None)

    # --- 규칙 5: 온도 이탈 ---
    temperature, _ = snapshot.latest_metric(conn, room_id, "temperature")
    target = room.get("target_temperature") or 24.0
    if temperature is not None and abs(temperature - target) > TEMPERATURE_DEVIATION_C:
        _upsert(conn, room_id, "temperature_abnormal", None,
                "실내 온도 범위 이탈",
                f"현재 {temperature:.1f}°C 로 목표 {target:.0f}°C 대비 "
                f"{abs(temperature - target):.1f}°C 벗어났습니다.")
    else:
        _resolve(conn, room_id, "temperature_abnormal", None)


def evaluate_all(conn: sqlite3.Connection) -> None:
    for room in conn.execute("SELECT * FROM rooms").fetchall():
        evaluate_room(conn, room)
