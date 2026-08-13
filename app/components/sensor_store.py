import json
from pathlib import Path

_STORE_PATH = Path(__file__).resolve().parents[2] / ".data" / "sensors.json"

_DEFAULT_TYPES = [
    ("env", "env_01", True),
    ("motion", "pir_02", True),
    ("ir", "ir_01", False),
    ("plug", "plug_01", True),
    ("door", "door_01", False),
]


def _default_sensors(room_id: str) -> list[dict]:
    return [
        {
            "id": f"{room_id}_{name}",
            "room_id": room_id,
            "name": name,
            "type": sensor_type,
            "enabled": enabled,
        }
        for sensor_type, name, enabled in _DEFAULT_TYPES
    ]


def _load_sensors() -> list[dict]:
    if not _STORE_PATH.exists():
        return []
    return json.loads(_STORE_PATH.read_text(encoding="utf-8"))


def _save_sensors(sensors: list[dict]) -> None:
    _STORE_PATH.parent.mkdir(parents=True, exist_ok=True)
    _STORE_PATH.write_text(
        json.dumps(sensors, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def list_sensors(room_id: str) -> list[dict]:
    sensors = _load_sensors()
    if any(sensor["room_id"] == room_id for sensor in sensors):
        return [sensor for sensor in sensors if sensor["room_id"] == room_id]
    seeded = _default_sensors(room_id)
    _save_sensors(sensors + seeded)
    return seeded


def set_sensor_enabled(sensor_id: str, enabled: bool) -> None:
    sensors = _load_sensors()
    sensor = next((s for s in sensors if s["id"] == sensor_id), None)
    if sensor is None:
        return
    sensor["enabled"] = enabled
    _save_sensors(sensors)
