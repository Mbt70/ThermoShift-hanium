"""기간별 KPI 집계.

성과 리포트 화면과 AI 리포트 생성이 같은 숫자를 쓰도록, 집계는 여기 한 곳에만 둔다.
KPI 정의는 README의 Baseline & KPI 표를 따른다.
"""

import json
import sqlite3
from collections import Counter
from datetime import date, timedelta
from typing import Optional

from .timeutil import local_day_range

# 목표 온도에서 이만큼 벗어나면 '이탈'로 센다.
TEMPERATURE_TOLERANCE_C = 2.0
CO2_THRESHOLD_PPM = 1000.0


def _period_bounds(start: date, end: date) -> tuple[str, str]:
    """로컬 날짜 구간(양끝 포함) → UTC ISO 경계."""
    start_utc, _ = local_day_range(start)
    _, end_utc = local_day_range(end)
    return start_utc, end_utc


def _round(value, digits: int = 1):
    return None if value is None else round(value, digits)


def _pct(part: int, total: int) -> Optional[float]:
    return None if not total else round(part / total * 100, 1)


def collect(conn: sqlite3.Connection, room_id: str, start: date, end: date) -> dict:
    room = conn.execute("SELECT * FROM rooms WHERE id = ?", (room_id,)).fetchone()
    if room is None:
        raise ValueError("공간을 찾을 수 없습니다.")
    room = dict(room)
    target = room.get("target_temperature") or 24.0
    start_utc, end_utc = _period_bounds(start, end)

    stats: dict = {
        "room_id": room_id,
        "room_name": room["name"],
        "target_temperature": target,
        "start": start.isoformat(),
        "end": end.isoformat(),
    }

    # --- 환경 ---
    for metric, prefix in (("temperature", "temp"), ("co2", "co2"), ("humidity", "humidity")):
        row = conn.execute(
            """
            SELECT COUNT(*) AS n, AVG(r.value) AS avg, MIN(r.value) AS min, MAX(r.value) AS max
            FROM sensor_readings r JOIN devices d ON d.id = r.device_id
            WHERE d.room_id = ? AND r.metric = ? AND r.value IS NOT NULL
                  AND (r.quality IS NULL OR r.quality != 'INVALID')
                  AND r.timestamp >= ? AND r.timestamp < ?
            """,
            (room_id, metric, start_utc, end_utc),
        ).fetchone()
        stats[f"{prefix}_count"] = row["n"]
        stats[f"{prefix}_avg"] = _round(row["avg"])
        stats[f"{prefix}_min"] = _round(row["min"])
        stats[f"{prefix}_max"] = _round(row["max"])

    # 목표 범위 이탈 비율 — 표본 기준(측정 주기가 일정하다는 가정)
    row = conn.execute(
        """
        SELECT SUM(CASE WHEN ABS(r.value - ?) > ? THEN 1 ELSE 0 END) AS out_of_range,
               COUNT(*) AS total
        FROM sensor_readings r JOIN devices d ON d.id = r.device_id
        WHERE d.room_id = ? AND r.metric = 'temperature' AND r.value IS NOT NULL
              AND (r.quality IS NULL OR r.quality != 'INVALID')
              AND r.timestamp >= ? AND r.timestamp < ?
        """,
        (target, TEMPERATURE_TOLERANCE_C, room_id, start_utc, end_utc),
    ).fetchone()
    stats["temp_out_of_range_pct"] = _pct(row["out_of_range"] or 0, row["total"] or 0)

    row = conn.execute(
        """
        SELECT SUM(CASE WHEN r.value > ? THEN 1 ELSE 0 END) AS high, COUNT(*) AS total
        FROM sensor_readings r JOIN devices d ON d.id = r.device_id
        WHERE d.room_id = ? AND r.metric = 'co2' AND r.value IS NOT NULL
              AND (r.quality IS NULL OR r.quality != 'INVALID')
              AND r.timestamp >= ? AND r.timestamp < ?
        """,
        (CO2_THRESHOLD_PPM, room_id, start_utc, end_utc),
    ).fetchone()
    stats["co2_high_pct"] = _pct(row["high"] or 0, row["total"] or 0)

    # --- 데이터 품질 ---
    row = conn.execute(
        """
        SELECT COUNT(*) AS total,
               SUM(CASE WHEN r.quality = 'INVALID' THEN 1 ELSE 0 END) AS invalid
        FROM sensor_readings r JOIN devices d ON d.id = r.device_id
        WHERE d.room_id = ? AND r.timestamp >= ? AND r.timestamp < ?
        """,
        (room_id, start_utc, end_utc),
    ).fetchone()
    stats["reading_count"] = row["total"]
    stats["invalid_pct"] = _pct(row["invalid"] or 0, row["total"] or 0)

    # --- 재실 ---
    rows = conn.execute(
        """
        SELECT state, COUNT(*) AS n FROM occupancy_estimates
        WHERE room_id = ? AND timestamp >= ? AND timestamp < ? GROUP BY state
        """,
        (room_id, start_utc, end_utc),
    ).fetchall()
    occupancy = {r["state"]: r["n"] for r in rows}
    total_occ = sum(occupancy.values())
    stats["occupancy_samples"] = total_occ
    stats["occupancy_states"] = occupancy
    stats["occupied_pct"] = _pct(occupancy.get("OCCUPIED", 0), total_occ)

    # --- 제어 ---
    rows = conn.execute(
        """
        SELECT control_mode, proposed_action, executed FROM control_decisions
        WHERE room_id = ? AND timestamp >= ? AND timestamp < ? ORDER BY timestamp
        """,
        (room_id, start_utc, end_utc),
    ).fetchall()
    stats["decision_count"] = len(rows)
    stats["executed_count"] = sum(1 for r in rows if r["executed"])
    stats["control_modes"] = dict(Counter(r["control_mode"] for r in rows))

    changes = 0
    previous = None
    for r in rows:
        if previous is not None and r["proposed_action"] != previous:
            changes += 1
        previous = r["proposed_action"]
    stats["action_changes"] = changes
    stats["actions"] = dict(Counter(r["proposed_action"] for r in rows))

    # 왜 그렇게 판단했는지 상위 사유 — 리포트에서 원인 설명에 쓴다
    reason_rows = conn.execute(
        """
        SELECT reason_codes_json FROM control_decisions
        WHERE room_id = ? AND timestamp >= ? AND timestamp < ?
        """,
        (room_id, start_utc, end_utc),
    ).fetchall()
    reasons: Counter = Counter()
    for r in reason_rows:
        for code in json.loads(r["reason_codes_json"] or "[]"):
            reasons[code] += 1
    stats["top_reason_codes"] = dict(reasons.most_common(8))

    # --- 수동 명령 ---
    rows = conn.execute(
        """
        SELECT status, COUNT(*) AS n FROM control_commands
        WHERE room_id = ? AND created_at >= ? AND created_at < ? GROUP BY status
        """,
        (room_id, start_utc, end_utc),
    ).fetchall()
    by_status = {r["status"]: r["n"] for r in rows}
    stats["command_sent"] = by_status.get("sent", 0)
    stats["command_failed"] = by_status.get("failed", 0)
    stats["command_pending"] = by_status.get("pending", 0)
    total_commands = stats["command_sent"] + stats["command_failed"]
    stats["command_success_pct"] = _pct(stats["command_sent"], total_commands)

    # --- 알림 ---
    rows = conn.execute(
        """
        SELECT type, COUNT(*) AS n FROM alerts
        WHERE room_id = ? AND created_at >= ? AND created_at < ? GROUP BY type
        """,
        (room_id, start_utc, end_utc),
    ).fetchall()
    stats["alert_counts"] = {r["type"]: r["n"] for r in rows}

    # 전력 실측 장비가 붙기 전까지는 에너지 KPI를 낼 수 없다.
    # 값을 지어내지 않고 없음을 명시한다.
    has_power = conn.execute(
        """
        SELECT COUNT(*) FROM sensor_readings r JOIN devices d ON d.id = r.device_id
        WHERE d.room_id = ? AND r.metric = 'power' AND r.timestamp >= ? AND r.timestamp < ?
        """,
        (room_id, start_utc, end_utc),
    ).fetchone()[0]
    stats["power_measured"] = bool(has_power)
    stats["energy_kwh"] = None

    return stats


def default_period(days: int = 7) -> tuple[date, date]:
    end = date.today()
    return end - timedelta(days=days - 1), end
