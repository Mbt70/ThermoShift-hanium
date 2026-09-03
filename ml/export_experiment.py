#!/usr/bin/env python3
"""DB의 실험 run을 재현 가능한 CSV 묶음과 manifest로 내보낸다.

사용 예:
    python -m ml.export_experiment 1

출력은 기본적으로 .data/experiments/run_0001 아래에 생성된다. 원본 DB는
수정하지 않는다. manifest의 quality_scope와 limitations를 확인하지 않은
데이터를 학습/성과 산출에 넣지 않는다.
"""

from __future__ import annotations

import argparse
import csv
import json
import statistics
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
GATEWAY_ROOT = ROOT / "gateway"
if str(GATEWAY_ROOT) not in sys.path:
    sys.path.insert(0, str(GATEWAY_ROOT))

from app.storage import get_storage  # noqa: E402


def _serializable(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return value


def _json_value(value: Any) -> Any:
    """JSON 구조를 유지하면서 datetime만 문자열로 바꾼다."""
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {key: _json_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_value(item) for item in value]
    return value


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        for row in rows:
            writer.writerow({key: _serializable(value) for key, value in row.items()})


def _sample_summary(rows: list[dict[str, Any]], time_key: str) -> dict[str, Any]:
    stamps = [row[time_key] for row in rows if row.get(time_key) is not None]
    intervals = [
        (right - left).total_seconds() for left, right in zip(stamps, stamps[1:])
        if right >= left
    ]
    return {
        "rows": len(rows),
        "first_at": stamps[0].isoformat() if stamps else None,
        "last_at": stamps[-1].isoformat() if stamps else None,
        "median_interval_sec": round(statistics.median(intervals), 3) if intervals else None,
        "max_interval_sec": round(max(intervals), 3) if intervals else None,
    }


def _phase_summary(
    env_rows: list[dict[str, Any]], events: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """실제 이벤트 경계 사이의 센서 변화와 온도 선형 기울기를 요약한다."""
    event_time = {
        event["event"]: datetime.fromisoformat(event["at"])
        for event in events if event.get("event") and event.get("at")
    }
    phase_bounds = (
        ("baseline", "run_start_all_off_door_closed", "heater_physical_on"),
        ("heater_on", "heater_physical_on", "heater_physical_off"),
        ("post_heat", "heater_physical_off", "door_open"),
        ("door_open", "door_open", "door_closed"),
        ("peltier_on", "peltier_on", "peltier_off"),
        ("recovery", "peltier_off", "run_end"),
    )
    summaries: list[dict[str, Any]] = []
    for name, start_event, end_event in phase_bounds:
        if start_event not in event_time or end_event not in event_time:
            continue
        start, end = event_time[start_event], event_time[end_event]
        rows = [row for row in env_rows if start <= row["measured_at"] <= end]
        if not rows:
            continue
        temperatures = [float(row["temperature"]) for row in rows]
        minutes = [(row["measured_at"] - rows[0]["measured_at"]).total_seconds() / 60.0 for row in rows]
        mean_x = sum(minutes) / len(minutes)
        mean_y = sum(temperatures) / len(temperatures)
        denominator = sum((value - mean_x) ** 2 for value in minutes)
        slope = (
            sum((x - mean_x) * (y - mean_y) for x, y in zip(minutes, temperatures))
            / denominator if denominator else 0.0
        )
        summary: dict[str, Any] = {
            "phase": name,
            "start_at": start,
            "end_at": end,
            "duration_sec": (end - start).total_seconds(),
            "samples": len(rows),
            "temperature_start_c": temperatures[0],
            "temperature_end_c": temperatures[-1],
            "temperature_delta_c": round(temperatures[-1] - temperatures[0], 4),
            "temperature_slope_c_per_min": round(slope, 5),
        }
        for column in ("humidity", "co2"):
            values = [float(row[column]) for row in rows if row.get(column) is not None]
            summary[f"{column}_start"] = values[0] if values else None
            summary[f"{column}_end"] = values[-1] if values else None
            summary[f"{column}_delta"] = round(values[-1] - values[0], 4) if values else None
        summaries.append(summary)
    return summaries


def export_run(run_id: int, output_root: Path) -> Path:
    storage = get_storage()
    try:
        with storage._pool.connection() as conn, conn.cursor() as cur:
            cur.execute("SELECT * FROM experiment_runs WHERE run_id = %s", (run_id,))
            run = cur.fetchone()
            if run is None:
                raise ValueError(f"experiment run {run_id} does not exist")

            start, end, room_id = run["started_at"], run["ends_at"], run["room_id"]
            specs = {
                "sensor_env": (
                    "SELECT se.* FROM sensor_env se JOIN devices d ON d.device_id=se.device_id "
                    "WHERE d.room_id=%s AND se.measured_at BETWEEN %s AND %s ORDER BY se.measured_at",
                    (room_id, start, end), "measured_at",
                ),
                "sensor_pir": (
                    "SELECT sp.* FROM sensor_pir sp JOIN devices d ON d.device_id=sp.device_id "
                    "WHERE d.room_id=%s AND sp.measured_at BETWEEN %s AND %s ORDER BY sp.measured_at",
                    (room_id, start, end), "measured_at",
                ),
                "sensor_door": (
                    "SELECT sd.* FROM sensor_door sd JOIN devices d ON d.device_id=sd.device_id "
                    "WHERE d.room_id=%s AND sd.measured_at BETWEEN %s AND %s ORDER BY sd.measured_at",
                    (room_id, start, end), "measured_at",
                ),
                "power_readings": (
                    "SELECT pr.* FROM power_readings pr JOIN devices d ON d.device_id=pr.device_id "
                    "WHERE d.room_id=%s AND pr.measured_at BETWEEN %s AND %s ORDER BY pr.measured_at",
                    (room_id, start, end), "measured_at",
                ),
                "heater_log": (
                    "SELECT * FROM heater_log WHERE run_id=%s ORDER BY recorded_at",
                    (run_id,), "recorded_at",
                ),
                "control_decisions": (
                    "SELECT * FROM control_decisions WHERE room_id=%s AND decided_at BETWEEN %s AND %s "
                    "ORDER BY decided_at",
                    (room_id, start, end), "decided_at",
                ),
                "occupancy_estimates": (
                    "SELECT oe.* FROM occupancy_estimates oe WHERE oe.estimated_at BETWEEN %s AND %s "
                    "ORDER BY oe.estimated_at",
                    (start, end), "estimated_at",
                ),
            }
            tables: dict[str, list[dict[str, Any]]] = {}
            time_keys: dict[str, str] = {}
            for name, (query, params, time_key) in specs.items():
                cur.execute(query, params)
                tables[name] = [dict(row) for row in cur.fetchall()]
                time_keys[name] = time_key
    finally:
        storage.close()

    output_dir = output_root / f"run_{run_id:04d}"
    output_dir.mkdir(parents=True, exist_ok=True)
    for name, rows in tables.items():
        _write_csv(output_dir / f"{name}.csv", rows)

    env_rows = tables["sensor_env"]
    temperatures = [float(row["temperature"]) for row in env_rows if row["temperature"] is not None]
    plan = run["plan"]
    events = plan.get("actual_events", []) if isinstance(plan, dict) else []
    phases = _phase_summary(env_rows, events)
    _write_csv(output_dir / "phase_summary.csv", phases)
    manifest = {
        "run": {key: _json_value(value) for key, value in dict(run).items()},
        "quality_scope": (
            plan.get("data_quality_scope", "UNREVIEWED")
            if isinstance(plan, dict) else "UNREVIEWED"
        ),
        "duration_sec": (end - start).total_seconds(),
        "tables": {
            name: _sample_summary(rows, time_keys[name]) for name, rows in tables.items()
        },
        "temperature": {
            "min_c": min(temperatures) if temperatures else None,
            "max_c": max(temperatures) if temperatures else None,
            "range_c": round(max(temperatures) - min(temperatures), 3) if temperatures else None,
        },
        "actual_events": events,
        "phase_summary": [
            {key: _serializable(value) for key, value in row.items()} for row in phases
        ],
        "limitations": [
            "20-minute pipeline pilot is too short for final RC/PINN identification.",
            "No electrical power readings were captured; energy optimization cannot be validated.",
            "Peltier events are command timestamps, not electrical feedback acknowledgements.",
            "Outdoor/ambient temperature was not independently measured.",
            "Initial commanded heater-ON rows were corrected to OFF after operator confirmed physical power was off.",
            "No physical heater-OFF timestamp was confirmed; phases after heater ON may be thermally confounded.",
            "Door-open duration followed sensor truth and differs from the original one-minute plan.",
        ],
    }
    (output_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, default=_serializable),
        encoding="utf-8",
    )
    return output_dir


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("run_id", type=int)
    parser.add_argument(
        "--output-root", type=Path, default=ROOT / ".data" / "experiments"
    )
    args = parser.parse_args()
    print(export_run(args.run_id, args.output_root))


if __name__ == "__main__":
    main()
