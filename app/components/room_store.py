import sys
from datetime import datetime
from pathlib import Path

_REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
if str(_REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPOSITORY_ROOT))

from shared.api_client import api_delete, api_get, api_patch, api_post

# UI control-mode buttons use "predictive" for the 4th mode (digital_twin.py's
# _CONTROL_MODES); the DB's control_mode enum spells the same mode "mpc".
_MODE_UI_TO_DB = {"predictive": "mpc"}
_MODE_DB_TO_UI = {"mpc": "predictive"}

# Power draw above this is treated as "AC is actually running" - there's no
# direct boolean for this in the schema, but seed data (and any real plug
# reading) runs ~950-1100W with cooling on vs a few W idle, so a simple
# threshold is a reasonable proxy.
_AC_ON_POWER_THRESHOLD_W = 50


def _with_latest(room: dict) -> dict:
    latest = api_get(f"/rooms/{room['id']}/latest", ignore_404=True) or {}
    env = latest.get("env") or {}
    power = latest.get("power") or {}
    occupancy = latest.get("occupancy") or {}
    power_w = power.get("power_w")
    room["temperature"] = env.get("temperature")
    room["humidity"] = env.get("humidity")
    room["co2"] = env.get("co2")
    room["power"] = power_w
    room["occupied"] = occupancy.get("occupancy_state") == "occupied"
    room["occupancy_count"] = occupancy.get("estimated_count")
    room["aircon_on"] = bool(power_w and power_w >= _AC_ON_POWER_THRESHOLD_W)
    room["sensor_connected"] = env.get("measured_at") is not None
    room["last_updated"] = env.get("measured_at") or room.get("last_updated")
    return room


def _from_api(row: dict) -> dict:
    room = {
        "id": row["room_id"],
        "owner_user_id": row["owner_user_id"],
        "name": row["name"],
        "location": row.get("location") or "",
        "floor_plan_name": row.get("floor_plan_url") or "",
        "target_temperature": round(row["target_temp"]),
        "control_mode": _MODE_DB_TO_UI.get(row["control_mode"], row["control_mode"]),
        "last_updated": row.get("updated_at"),
    }
    return _with_latest(room)


def list_rooms(owner_user_id: int) -> list[dict]:
    if owner_user_id is None:
        return []
    rows = api_get("/rooms", params={"owner_user_id": owner_user_id}) or []
    return [_from_api(row) for row in rows]


def get_room(room_id: int) -> dict | None:
    row = api_get(f"/rooms/{room_id}", ignore_404=True)
    return _from_api(row) if row else None


def register_room(name: str, location: str, floor_plan_name: str, owner_user_id: int) -> dict:
    row = api_post(
        "/rooms",
        json={
            "owner_user_id": owner_user_id,
            "name": name,
            "location": location,
            "floor_plan_url": floor_plan_name or None,
        },
    )
    return _from_api(row)


def room_status(room: dict) -> str:
    if not room.get("sensor_connected"):
        return "오류"
    if room["temperature"] is not None and room["temperature"] >= 27:
        return "주의"
    return "정상"


def comfort_index(room: dict) -> int:
    temp = room["temperature"]
    if temp is None:
        return 0
    target = room.get("target_temperature", 24)
    co2 = room.get("co2") or 600
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
    occupancy = "재실 중" if room.get("occupied") else "공실"
    if temp is None:
        headline = f"{occupancy} · 센서 데이터 없음"
    else:
        diff = temp - target
        if diff > 1:
            comparison, action = "초과", "냉방 강화 권장"
        elif diff < -1:
            comparison, action = "미달", "냉방 완화 권장"
        else:
            comparison, action = "근접", "현재 설정 유지"
        headline = f"{occupancy} · 온도 {temp:.1f}°C로 목표({target}°C) {comparison} → {action}"
    aircon_state = "ON" if room.get("aircon_on") else "OFF"
    subline = f"규칙 rule-01 · 냉방 {aircon_state} · 목표 {target}°C"
    return headline, subline


def ai_judgment(room: dict) -> tuple[str, str] | None:
    """AI(Gemini)가 최근 제어 판단을 설명한 문장. 사용 불가하면 None.

    호출부는 None 이면 system_judgment() 로 폴백해야 한다 - AI 는 부가
    기능이지 전제가 아니다.
    """
    try:
        status = api_get("/ai/status")
        if not status or not status.get("available"):
            return None
        decision = api_get(f"/rooms/{room['id']}/decisions/latest", ignore_404=True)
        if decision is None:
            return None
        explanation = api_post(f"/ai/decisions/{decision['decision_id']}/explain")
    except Exception:
        return None
    if not explanation or not explanation.get("headline") or not explanation.get("detail"):
        return None
    headline = explanation["headline"]
    subline = explanation["detail"]
    if explanation.get("recommendation"):
        subline = f"{subline} {explanation['recommendation']}"
    return headline, subline


def trend_series(room: dict, points: int = 30) -> tuple[list[float], list[float]]:
    """Real temperature/CO2 history for the room's env sensor, most recent
    `points` minutes. Returns two empty lists if there's no env device or no
    readings in that window yet (a brand-new room, or one whose sensor hasn't
    reported recently) - callers should handle that rather than getting a
    synthetic fallback series.
    """
    readings = api_get(f"/rooms/{room['id']}/trend", params={"minutes": points}) or []
    temps = [r["temperature"] for r in readings if r["temperature"] is not None]
    co2s = [r["co2"] for r in readings if r["co2"] is not None]
    return temps, co2s


def environment_snapshot(room: dict) -> dict:
    return {
        "temperature": room.get("temperature"),
        "humidity": room.get("humidity"),
        "co2": room.get("co2"),
        "power": round(room["power"] / 1000, 2) if room.get("power") is not None else None,
    }


def relative_updated(room: dict) -> str:
    last_updated = room.get("last_updated")
    if not last_updated:
        return "방금"
    if isinstance(last_updated, str):
        last_updated = datetime.fromisoformat(last_updated)
    now = datetime.now(last_updated.tzinfo) if last_updated.tzinfo else datetime.now()
    seconds = int((now - last_updated).total_seconds())
    if seconds < 60:
        return f"{max(seconds, 0)}초 전"
    minutes = seconds // 60
    if minutes < 60:
        return f"{minutes}분 전"
    return f"{minutes // 60}시간 전"


def set_target_temperature(room_id: int, target_temperature: int) -> None:
    api_patch(f"/rooms/{room_id}/target-temp", json={"target_temp": target_temperature})


def set_control_mode(room_id: int, control_mode: str) -> None:
    db_mode = _MODE_UI_TO_DB.get(control_mode, control_mode)
    api_patch(f"/rooms/{room_id}/control-mode", json={"control_mode": db_mode})


def update_room(room_id: int, *, name: str, location: str, floor_plan_name: str | None) -> None:
    api_patch(
        f"/rooms/{room_id}",
        json={"name": name, "location": location, "floor_plan_url": floor_plan_name or None},
    )


def delete_room(room_id: int) -> None:
    api_delete(f"/rooms/{room_id}", ignore_404=True)
