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
from datetime import datetime, timedelta
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


def _event_times(events: list[dict[str, Any]]) -> dict[str, datetime]:
    return {
        event["event"]: datetime.fromisoformat(event["at"])
        for event in events if event.get("event") and event.get("at")
    }


def _event_sources(events: list[dict[str, Any]]) -> dict[str, str]:
    return {
        event["event"]: str(event.get("source", ""))
        for event in events if event.get("event")
    }


def _model_timeline_30s(
    run_id: int,
    started_at: datetime,
    tables: dict[str, list[dict[str, Any]]],
    events: list[dict[str, Any]],
    quality_scope: str,
) -> list[dict[str, Any]]:
    """센서와 입력을 30초 격자로 맞춘 학습 후보 표를 만든다.

    명령을 실제 출력으로 둔갑시키지 않도록 commanded와 verified를 분리한다.
    물리 상태가 확인되지 않은 run은 CSV를 만들되 training_eligible=false다.
    """
    env_rows = tables["sensor_env"]
    if not env_rows:
        return []

    buckets: dict[int, list[dict[str, Any]]] = {}
    for row in env_rows:
        index = int((row["measured_at"] - started_at).total_seconds() // 30)
        buckets.setdefault(index, []).append(row)

    times = _event_times(events)
    sources = _event_sources(events)
    peltier_on, peltier_off = times.get("peltier_on"), times.get("peltier_off")
    cooling_verified = bool(
        peltier_on
        and peltier_off
        and sources.get("peltier_on") == "device_state_ack"
        and sources.get("peltier_off") == "device_state_ack"
    )
    heater_on, heater_off = (
        times.get("heater_physical_on"),
        times.get("heater_physical_off"),
    )

    def average(rows: list[dict[str, Any]], key: str) -> float | None:
        values = [float(row[key]) for row in rows if row.get(key) is not None]
        return round(sum(values) / len(values), 5) if values else None

    out: list[dict[str, Any]] = []
    previous_temp: float | None = None
    previous_at: datetime | None = None
    for index, rows in sorted(buckets.items()):
        at = started_at + timedelta(seconds=index * 30)
        end_at = at + timedelta(seconds=30)
        temperature = average(rows, "temperature")

        pir_in_bin = [
            row for row in tables["sensor_pir"]
            if at <= row["measured_at"] < end_at
        ]
        door_in_bin = [
            row for row in tables["sensor_door"]
            if at <= row["measured_at"] < end_at
        ]
        heater_before_end = [
            row for row in tables["heater_log"] if row["recorded_at"] < end_at
        ]
        latest_heater = heater_before_end[-1] if heater_before_end else None

        if heater_on is None or at < heater_on:
            heater_physical_u: int | None = 0
            heater_state_verified = True
        elif heater_off is not None:
            heater_physical_u = int(at < heater_off)
            heater_state_verified = True
        else:
            heater_physical_u = None
            heater_state_verified = False

        cooling_u = int(bool(peltier_on and peltier_off and peltier_on <= at < peltier_off))
        actuation_verified = bool(cooling_verified or cooling_u == 0)
        training_eligible = bool(
            quality_scope == "TRAINING_QUALITY_APPROVED"
            and heater_state_verified
            and actuation_verified
        )

        dt_seconds = (at - previous_at).total_seconds() if previous_at else None
        d_temp = (
            (temperature - previous_temp) / dt_seconds * 60.0
            if temperature is not None and previous_temp is not None and dt_seconds
            else None
        )
        if peltier_on and peltier_off and peltier_on <= at < peltier_off:
            phase = "peltier_commanded_on"
        elif times.get("door_open") and times.get("door_closed") and (
            times["door_open"] <= at < times["door_closed"]
        ):
            phase = "door_open"
        elif heater_on and at >= heater_on:
            phase = "post_heater_on_state_unverified" if heater_off is None else "heater_cycle"
        else:
            phase = "baseline"

        out.append({
            "run_id": run_id,
            "measured_at": at,
            "temperature": temperature,
            "humidity": average(rows, "humidity"),
            "co2": average(rows, "co2"),
            "pir_motion": any(bool(row.get("motion")) for row in pir_in_bin),
            "door_open_fraction": (
                round(sum(row.get("door_state") == "open" for row in door_in_bin)
                      / len(door_in_bin), 4)
                if door_in_bin else None
            ),
            "heater_commanded_duty": (
                int(latest_heater["requested_duty"]) if latest_heater else 0
            ),
            "heater_physical_u": heater_physical_u,
            "heater_state_verified": heater_state_verified,
            "cooling_u": cooling_u,
            "actuation_verified": actuation_verified,
            "dt_seconds": dt_seconds,
            "dT_dt": round(d_temp, 6) if d_temp is not None else None,
            "phase": phase,
            "quality_scope": quality_scope,
            "training_eligible": training_eligible,
        })
        previous_temp, previous_at = temperature, at
    return out


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
    quality_scope = (
        plan.get("data_quality_scope", "UNREVIEWED")
        if isinstance(plan, dict) else "UNREVIEWED"
    )
    phases = _phase_summary(env_rows, events)
    timeline = _model_timeline_30s(
        run_id, start, tables, events, quality_scope
    )
    _write_csv(output_dir / "phase_summary.csv", phases)
    _write_csv(output_dir / "model_timeline_30s.csv", timeline)
    manifest = {
        "run": {key: _json_value(value) for key, value in dict(run).items()},
        "quality_scope": quality_scope,
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
        "derived_files": {
            "model_timeline_30s.csv": {
                "rows": len(timeline),
                "purpose": "pipeline/training candidate with command and verification flags",
                "training_eligible_rows": sum(
                    bool(row["training_eligible"]) for row in timeline
                ),
            }
        },
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
