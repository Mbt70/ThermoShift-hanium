from datetime import datetime, timedelta, timezone

from ml.export_experiment import _model_timeline_30s


def test_물리_ACK가_없는_명령은_학습입력이_되지_않는다():
    start = datetime(2026, 9, 4, tzinfo=timezone.utc)
    tables = {
        "sensor_env": [
            {
                "measured_at": start + timedelta(seconds=seconds),
                "temperature": 24.0 + seconds / 1000,
                "humidity": 50.0,
                "co2": 500,
            }
            for seconds in range(0, 120, 5)
        ],
        "sensor_pir": [],
        "sensor_door": [],
        "heater_log": [],
    }
    events = [
        {"event": "peltier_on", "at": (start + timedelta(seconds=30)).isoformat(),
         "source": "operator_command"},
        {"event": "peltier_off", "at": (start + timedelta(seconds=90)).isoformat(),
         "source": "systemd_timer"},
    ]
    rows = _model_timeline_30s(
        1, start, tables, events, "TRAINING_QUALITY_APPROVED"
    )
    on_rows = [row for row in rows if row["cooling_u"] == 1]
    assert on_rows
    assert all(not row["actuation_verified"] for row in on_rows)
    assert all(not row["training_eligible"] for row in on_rows)


def test_장치_ACK와_승인된_run은_학습후보가_된다():
    start = datetime(2026, 9, 4, tzinfo=timezone.utc)
    tables = {
        "sensor_env": [
            {"measured_at": start, "temperature": 24.0, "humidity": 50, "co2": 500},
            {"measured_at": start + timedelta(seconds=35), "temperature": 23.9,
             "humidity": 50, "co2": 500},
        ],
        "sensor_pir": [],
        "sensor_door": [],
        "heater_log": [],
    }
    events = [
        {"event": "peltier_on", "at": start.isoformat(), "source": "device_state_ack"},
        {"event": "peltier_off", "at": (start + timedelta(seconds=60)).isoformat(),
         "source": "device_state_ack"},
    ]
    rows = _model_timeline_30s(
        2, start, tables, events, "TRAINING_QUALITY_APPROVED"
    )
    assert rows
    assert all(row["actuation_verified"] for row in rows)
    assert all(row["training_eligible"] for row in rows)
