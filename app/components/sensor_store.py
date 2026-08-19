import sys
from pathlib import Path

_REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
if str(_REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPOSITORY_ROOT))

from shared.api_client import api_get, api_patch

_TYPE_LABELS = {
    "env": "온습도 CO2 센서",
    "pir": "인체감지 센서",
    "ir": "IR 송신기",
    "plug": "스마트 플러그 (전력)",
    "door": "도어 센서",
}


def sensor_type_label(sensor_type: str) -> str:
    return _TYPE_LABELS.get(sensor_type, sensor_type)


def _from_api(row: dict) -> dict:
    return {
        "id": row["device_id"],
        "room_id": row["room_id"],
        "name": row["device_code"],
        "type": row["device_type"],
        "enabled": row["is_enabled"],
        "location": row.get("install_location") or "",
        "status": row["comm_status"],  # "normal" | "offline" | "error" | "unknown"
    }


def list_sensors(room_id: int) -> list[dict]:
    rows = api_get(f"/rooms/{room_id}/devices") or []
    return [_from_api(row) for row in rows]


def set_sensor_enabled(sensor_id: int, enabled: bool) -> None:
    api_patch(f"/devices/{sensor_id}/enabled", json={"is_enabled": enabled})
