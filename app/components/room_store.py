import json
import random
import uuid
from datetime import datetime, timezone
from pathlib import Path

from . import backend

_STORE_PATH = Path(__file__).resolve().parents[2] / ".data" / "rooms.json"


_DEFAULT_FIELDS = {
    "co2": 600,
    "occupied": False,
    "target_temperature": 24,
    "auto_control": True,
    "reservation_count": 0,
    "last_updated": None,
    "control_mode": "rule",
    "owner_email": None,
}


def _load_rooms() -> list[dict]:
    if not _STORE_PATH.exists():
        return []
    rooms = json.loads(_STORE_PATH.read_text(encoding="utf-8"))
    for room in rooms:
        for field, default in _DEFAULT_FIELDS.items():
            room.setdefault(field, default)
    return rooms


def _save_rooms(rooms: list[dict]) -> None:
    _STORE_PATH.parent.mkdir(parents=True, exist_ok=True)
    _STORE_PATH.write_text(
        json.dumps(rooms, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def list_rooms(owner_email: str) -> list[dict]:
    rooms = backend.get("/api/rooms", {"owner_email": owner_email})
    if rooms is not None:
        return rooms
    return [room for room in _load_rooms() if room.get("owner_email") == owner_email]


def get_room(room_id: str) -> dict | None:
    room = backend.get(f"/api/rooms/{room_id}")
    if room is not None:
        return room
    return next((room for room in _load_rooms() if room["id"] == room_id), None)


def register_room(name: str, location: str, floor_plan_name: str, owner_email: str) -> dict:
    created = backend.post(
        "/api/rooms",
        {
            "name": name,
            "location": location,
            "floor_plan_name": floor_plan_name,
            "owner_email": owner_email,
        },
    )
    if created is not None:
        return created

    rooms = _load_rooms()
    room = {
        "id": uuid.uuid4().hex,
        "name": name,
        "location": location,
        "floor_plan_name": floor_plan_name,
        "temperature": round(random.uniform(20.0, 28.0), 1),
        "co2": random.randint(500, 1100),
        "occupied": random.choice([True, False]),
        "aircon_on": random.choice([True, False]),
        "sensor_connected": random.choice([True, False]),
        "target_temperature": 24,
        "auto_control": True,
        "reservation_count": random.randint(0, 5),
        "last_updated": datetime.now().isoformat(),
        "owner_email": owner_email,
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


def comfort_index(room: dict) -> int:
    temp = room["temperature"]
    # 센서 데이터가 아직 없으면 점수를 매길 근거가 없다.
    if temp is None:
        return 0
    target = room.get("target_temperature", 24)
    co2 = room.get("co2", 600)
    score = 100.0
    score -= min(abs(temp - target) * 12, 60)
    score -= max(co2 - 800, 0) * 0.05
    return max(0, min(100, round(score)))


def comfort_label(score: int) -> str:
    if score >= 70:
        return "좋음"
    if score >= 40:
        return "보통"
    return "나쁨"


def system_judgment(room: dict) -> tuple[str, str]:
    temp = room["temperature"]
    target = room.get("target_temperature", 24)
    if temp is None:
        return (
            "센서 데이터 없음 → 제어 판단 불가",
            f"목표 {target}°C · 센서 연결을 확인해 주세요",
        )
    diff = temp - target
    occupancy = "재실 중" if room.get("occupied") else "공실"
    if diff > 1:
        comparison, action = "초과", "냉방 강화 권장"
    elif diff < -1:
        comparison, action = "미달", "냉방 완화 권장"
    else:
        comparison, action = "근접", "현재 설정 유지"
    headline = (
        f"{occupancy} · 온도 {temp:.1f}°C로 목표({target}°C) {comparison} → {action}"
    )
    aircon_state = "ON" if room["aircon_on"] else "OFF"
    subline = f"규칙 rule-01 · 냉방 {aircon_state} · 목표 {target}°C"
    return headline, subline


def _fill_gaps(series: list, fallback: float) -> list[float]:
    """빈 버킷(측정 없음)을 직전 값으로 채운다.

    센서가 잠깐 끊긴 구간 때문에 차트가 끊어져 보이는 것을 막는다.
    맨 앞이 비어 있으면 첫 실측값으로 소급해 채운다.
    """
    values = [point.get("value") for point in series]
    filled: list[float] = []
    last = None
    for value in values:
        if value is not None:
            last = value
        filled.append(last)

    first_known = next((v for v in filled if v is not None), fallback)
    return [v if v is not None else first_known for v in filled]


def trend_series(room: dict, points: int = 30) -> tuple[list[float], list[float]]:
    if backend.api_enabled():
        params = {"hours": 3, "points": points}
        temp_res = backend.get(f"/api/rooms/{room['id']}/trend", {**params, "metric": "temperature"})
        co2_res = backend.get(f"/api/rooms/{room['id']}/trend", {**params, "metric": "co2"})
        if temp_res and co2_res:
            temp_series = temp_res["series"]
            co2_series = co2_res["series"]
            # 전 구간이 비어 있으면(수집 이력 없음) 목데이터로 폴백한다.
            if any(p["value"] is not None for p in temp_series):
                temps = _fill_gaps(temp_series, room.get("temperature") or 24.0)
                co2s = _fill_gaps(co2_series, room.get("co2") or 600.0)
                return temps, co2s

    rng = random.Random(room["id"])
    temp = room["temperature"] if room["temperature"] is not None else 24.0
    co2 = room.get("co2") or 600
    start_temp = temp - rng.uniform(1.0, 2.5)
    start_co2 = co2 - rng.uniform(80, 200)
    temps = []
    co2s = []
    for i in range(points):
        t = i / (points - 1)
        temps.append(
            round(start_temp + (temp - start_temp) * t + rng.uniform(-0.15, 0.15), 2)
        )
        co2s.append(
            round(start_co2 + (co2 - start_co2) * t + rng.uniform(-15, 15), 1)
        )
    return temps, co2s


def environment_snapshot(room: dict) -> dict:
    rng = random.Random(f"{room['id']}-env")
    temp = room["temperature"]
    co2 = room.get("co2") or 600

    # API가 실측 습도/전력을 주면 그대로 쓰고, 없을 때만 추정값을 만든다.
    humidity = room.get("humidity")
    if humidity is None:
        base_temp = temp if temp is not None else 24.0
        humidity = max(30.0, min(70.0, 55 - (base_temp - 24) * 1.5 + rng.uniform(-4, 4)))
    power = room.get("power")
    if power is None:
        base_power = 1.8 if room.get("aircon_on") else 0.15
        power = max(0.0, base_power + rng.uniform(-0.2, 0.2))
    return {
        "temperature": temp,
        "humidity": round(humidity, 1),
        "co2": co2,
        "power": round(power, 2),
    }




def relative_updated(room: dict) -> str:
    last_updated = room.get("last_updated")
    if not last_updated:
        return "방금"
    try:
        updated_at = datetime.fromisoformat(last_updated)
    except (TypeError, ValueError):
        return "방금"
    # API는 UTC aware ISO를, 로컬 목데이터는 naive ISO를 준다. 기준을 맞춘다.
    if updated_at.tzinfo is None:
        now = datetime.now()
    else:
        now = datetime.now(timezone.utc)
    seconds = int((now - updated_at).total_seconds())
    if seconds < 60:
        return f"{max(seconds, 0)}초 전"
    minutes = seconds // 60
    if minutes < 60:
        return f"{minutes}분 전"
    return f"{minutes // 60}시간 전"


def set_target_temperature(room_id: str, target_temperature: int) -> None:
    if backend.patch(f"/api/rooms/{room_id}", {"target_temperature": target_temperature}) is not None:
        return

    rooms = _load_rooms()
    room = next((r for r in rooms if r["id"] == room_id), None)
    if room is None:
        return
    room["target_temperature"] = target_temperature
    room["last_updated"] = datetime.now().isoformat()
    _save_rooms(rooms)


def set_control_mode(room_id: str, control_mode: str) -> None:
    if backend.patch(f"/api/rooms/{room_id}", {"control_mode": control_mode}) is not None:
        return

    rooms = _load_rooms()
    room = next((r for r in rooms if r["id"] == room_id), None)
    if room is None:
        return
    room["control_mode"] = control_mode
    _save_rooms(rooms)


def update_room(
    room_id: str, *, name: str, location: str, floor_plan_name: str | None
) -> None:
    payload = {"name": name, "location": location}
    if floor_plan_name:
        payload["floor_plan_name"] = floor_plan_name
    if backend.patch(f"/api/rooms/{room_id}", payload) is not None:
        return

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
    if backend.delete(f"/api/rooms/{room_id}") is not None:
        return
    rooms = [room for room in _load_rooms() if room["id"] != room_id]
    _save_rooms(rooms)
