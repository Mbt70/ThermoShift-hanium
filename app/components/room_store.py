import json
import random
import uuid
from pathlib import Path

_STORE_PATH = Path(__file__).resolve().parents[2] / ".data" / "rooms.json"


def _load_rooms() -> list[dict]:
    if not _STORE_PATH.exists():
        return []
    return json.loads(_STORE_PATH.read_text(encoding="utf-8"))


def _save_rooms(rooms: list[dict]) -> None:
    _STORE_PATH.parent.mkdir(parents=True, exist_ok=True)
    _STORE_PATH.write_text(
        json.dumps(rooms, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def list_rooms() -> list[dict]:
    return _load_rooms()


def get_room(room_id: str) -> dict | None:
    return next((room for room in _load_rooms() if room["id"] == room_id), None)


def register_room(name: str, location: str, floor_plan_name: str) -> dict:
    rooms = _load_rooms()
    room = {
        "id": uuid.uuid4().hex,
        "name": name,
        "location": location,
        "floor_plan_name": floor_plan_name,
        "temperature": round(random.uniform(20.0, 28.0), 1),
        "aircon_on": random.choice([True, False]),
        "sensor_connected": random.choice([True, False]),
    }
    rooms.append(room)
    _save_rooms(rooms)
    return room


def room_status(room: dict) -> str:
    if not room.get("sensor_connected"):
        return "오류"
    if room["temperature"] is not None and room["temperature"] >= 27:
        return "주의"
    return "정상"


def update_room(
    room_id: str, *, name: str, location: str, floor_plan_name: str | None
) -> None:
    rooms = _load_rooms()
    room = next((r for r in rooms if r["id"] == room_id), None)
    if room is None:
        return
    room["name"] = name
    room["location"] = location
    if floor_plan_name:
        room["floor_plan_name"] = floor_plan_name
    _save_rooms(rooms)


def delete_room(room_id: str) -> None:
    rooms = [room for room in _load_rooms() if room["id"] != room_id]
    _save_rooms(rooms)
