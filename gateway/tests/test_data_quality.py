from datetime import datetime, timezone

from app.data_quality import DataQuality
from app.models import EnvData


class CaptureStorage:
    def __init__(self):
        self.readings = []

    def register_device(self, *_args):
        return 1

    def insert_sensor_reading(self, *args):
        self.readings.append(args)


def test_invalid_metric_does_not_mark_valid_siblings_as_error():
    quality = DataQuality.__new__(DataQuality)
    quality.storage = CaptureStorage()
    quality.last_seen = {}
    quality.latest_env = {}
    quality.latest_occ = {}
    raw = '{"node":"env_01","temperature":99,"humidity":50,"co2":800}'
    data = EnvData(
        device_id="env_01",
        timestamp=datetime.now(timezone.utc),
        temperature_c=99,
        humidity_rh=50,
        co2_ppm=800,
        raw_payload=raw,
    )

    quality.process_env(data, raw)

    assert [row[2] for row in quality.storage.readings] == ["humidity", "co2"]
    assert all(row[4] == "OK" for row in quality.storage.readings)
    assert all(row[5] == raw for row in quality.storage.readings)
