import json
from pathlib import Path

from . import backend

_STORE_PATH = Path(__file__).resolve().parents[2] / ".data" / "sensors.json"

_TYPE_LABELS = {
    "env": "온습도 CO2 센서",
    "pir": "인체감지 센서",
    "ir": "IR 송신기",
    "plug": "스마트 플러그 (전력)",
    "door": "도어 센서",
}

# (type, name, enabled, location, connection status ("success"/"disconnected"/None))
# type/name prefix follows the device_type spec: env/pir/door/ir/plug.
# location text follows the enclosure's internal layout diagram - env
# (SHT31+SCD41) sits in the top 환경 측정 영역, PIR/IR share the front-bottom
# OCC 노드 slot.
_DEFAULT_TYPES = [
    ("env", "env_01", True, "상단 환경 측정부", "success"),
    ("ir", "ir_01", True, "정면 하단 (OCC 노드)", "disconnected"),
    ("pir", "pir_01", True, "정면 하단 (OCC 노드)", None),
    ("door", "door_01", True, "문틀", None),
    ("plug", "plug_01", True, "", None),
    ("env", "env_04", False, "", None),
    ("ir", "ir_02", False, "", None),
]


def sensor_type_label(sensor_type: str) -> str:
    return _TYPE_LABELS.get(sensor_type, sensor_type)


def _default_sensors(room_id: str) -> list[dict]:
    return [
        {
            "id": f"{room_id}_{name}",
            "room_id": room_id,
            "name": name,
            "type": sensor_type,
            "enabled": enabled,
            "location": location,
            "status": status,
        }
        for sensor_type, name, enabled, location, status in _DEFAULT_TYPES
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
    # API의 devices 응답은 이미 센서 dict와 같은 키를 갖는다
    # (id / room_id / name / type / enabled / location / status).
    devices = backend.get(f"/api/rooms/{room_id}/devices")
    if devices is not None:
        return devices

    sensors = _load_sensors()
    if any(sensor["room_id"] == room_id for sensor in sensors):
        return [sensor for sensor in sensors if sensor["room_id"] == room_id]
    seeded = _default_sensors(room_id)
    _save_sensors(sensors + seeded)
    return seeded


def set_sensor_enabled(sensor_id: str, enabled: bool) -> None:
    if backend.patch(f"/api/devices/{sensor_id}", {"enabled": enabled}) is not None:
        return

    sensors = _load_sensors()
    sensor = next((s for s in sensors if s["id"] == sensor_id), None)
    if sensor is None:
        return
    sensor["enabled"] = enabled
    _save_sensors(sensors)
