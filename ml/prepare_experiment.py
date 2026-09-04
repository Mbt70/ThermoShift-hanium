#!/usr/bin/env python3
"""내보낸 실험 CSV를 30초 학습 후보표와 품질 보고서로 변환한다.

DB나 네트워크 없이 라즈베리파이에서 실행할 수 있다.

    python -m ml.prepare_experiment .data/experiments/run_0001
"""

from __future__ import annotations

import argparse
import csv
import json
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

from ml.export_experiment import _model_timeline_30s, _write_csv
from ml.training_quality import assess_training_frame


def _read_csv(path: Path) -> list[dict[str, Any]]:
    if not path.exists() or path.stat().st_size == 0:
        return []
    with path.open(encoding="utf-8", newline="") as handle:
        return [dict(row) for row in csv.DictReader(handle)]


def _load_tables(input_dir: Path) -> dict[str, list[dict[str, Any]]]:
    tables = {
        name: _read_csv(input_dir / f"{name}.csv")
        for name in ("sensor_env", "sensor_pir", "sensor_door", "heater_log")
    }
    for row in tables["sensor_env"]:
        row["measured_at"] = datetime.fromisoformat(row["measured_at"])
        for key in ("temperature", "humidity", "co2"):
            row[key] = float(row[key]) if row.get(key) else None
    for row in tables["sensor_pir"]:
        row["measured_at"] = datetime.fromisoformat(row["measured_at"])
        row["motion"] = str(row.get("motion", "")).lower() in {"true", "1"}
    for row in tables["sensor_door"]:
        row["measured_at"] = datetime.fromisoformat(row["measured_at"])
    for row in tables["heater_log"]:
        row["recorded_at"] = datetime.fromisoformat(row["recorded_at"])
        row["requested_duty"] = int(row["requested_duty"])
    return tables


def prepare(input_dir: Path) -> tuple[Path, Path]:
    manifest_path = input_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    run = manifest["run"]
    started_at = datetime.fromisoformat(run["started_at"])
    rows = _model_timeline_30s(
        int(run["run_id"]),
        started_at,
        _load_tables(input_dir),
        manifest.get("actual_events", []),
        str(manifest.get("quality_scope", "UNREVIEWED")),
    )

    timeline_path = input_dir / "model_timeline_30s.csv"
    _write_csv(timeline_path, rows)
    report = assess_training_frame(pd.DataFrame(rows))
    report_path = input_dir / "training_quality.json"
    report_path.write_text(
        json.dumps(report.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return timeline_path, report_path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("input_dir", type=Path)
    args = parser.parse_args()
    timeline, report = prepare(args.input_dir)
    print(timeline)
    print(report)


if __name__ == "__main__":
    main()
