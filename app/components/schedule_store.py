import json
import uuid
from datetime import date, datetime, time, timedelta
from pathlib import Path

from . import backend

_STORE_PATH = Path(__file__).resolve().parents[2] / ".data" / "schedules.json"

_WEEKDAY_CODES = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
_WEEKDAY_LABELS = {
    "mon": "월",
    "tue": "화",
    "wed": "수",
    "thu": "목",
    "fri": "금",
    "sat": "토",
    "sun": "일",
}

_DEFAULT_FIELDS = {
    "title": "",
    "precool_enabled": False,
    "precool_minutes_before": 20,
    "repeat_enabled": False,
    "repeat_days": [],
}


def _load_schedules() -> list[dict]:
    if not _STORE_PATH.exists():
        return []
    schedules = json.loads(_STORE_PATH.read_text(encoding="utf-8"))
    for schedule in schedules:
        for field, default in _DEFAULT_FIELDS.items():
            schedule.setdefault(field, default)
    return schedules


def _save_schedules(schedules: list[dict]) -> None:
    _STORE_PATH.parent.mkdir(parents=True, exist_ok=True)
    _STORE_PATH.write_text(
        json.dumps(schedules, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def list_schedules(room_id: str) -> list[dict]:
    remote = backend.get("/api/schedules", {"room_id": room_id})
    if remote is not None:
        return sorted(remote, key=lambda s: s["start_time"])

    schedules = [s for s in _load_schedules() if s["room_id"] == room_id]
    return sorted(schedules, key=lambda s: s["start_time"])


def list_today_schedules(room_id: str) -> list[dict]:
    today = date.today()
    today_code = _WEEKDAY_CODES[today.weekday()]
    schedules = []
    for schedule in list_schedules(room_id):
        is_anchor_date = schedule["date"] == today.isoformat()
        is_repeat_today = schedule["repeat_enabled"] and today_code in schedule["repeat_days"]
        if is_anchor_date or is_repeat_today:
            schedules.append(schedule)
    return schedules


def get_schedule(schedule_id: str) -> dict | None:
    remote = backend.get(f"/api/schedules/{schedule_id}")
    if remote is not None:
        return remote
    return next(
        (s for s in _load_schedules() if s["id"] == schedule_id), None
    )


def create_schedule(
    *,
    room_id: str,
    title: str = "",
    schedule_date: date,
    start_time: time,
    end_time: time,
    target_temperature: int,
    precool_enabled: bool,
    precool_minutes_before: int,
    repeat_enabled: bool,
    repeat_days: list[str],
) -> dict:
    payload = {
        "title": title,
        "date": schedule_date.isoformat(),
        "start_time": start_time.strftime("%H:%M"),
        "end_time": end_time.strftime("%H:%M"),
        "target_temperature": target_temperature,
        "precool_enabled": precool_enabled,
        "precool_minutes_before": precool_minutes_before,
        "repeat_enabled": repeat_enabled,
        "repeat_days": repeat_days,
    }
    created = backend.post("/api/schedules", json=payload, params={"room_id": room_id})
    if created is not None:
        return created

    schedules = _load_schedules()
    schedule = {
        "id": uuid.uuid4().hex,
        "room_id": room_id,
        "title": title,
        "date": schedule_date.isoformat(),
        "start_time": start_time.strftime("%H:%M"),
        "end_time": end_time.strftime("%H:%M"),
        "target_temperature": target_temperature,
        "precool_enabled": precool_enabled,
        "precool_minutes_before": precool_minutes_before,
        "repeat_enabled": repeat_enabled,
        "repeat_days": repeat_days,
        "created_at": datetime.now().isoformat(),
    }
    schedules.append(schedule)
    _save_schedules(schedules)
    return schedule


def update_schedule(
    schedule_id: str,
    *,
    title: str = "",
    schedule_date: date,
    start_time: time,
    end_time: time,
    target_temperature: int,
    precool_enabled: bool,
    precool_minutes_before: int,
    repeat_enabled: bool,
    repeat_days: list[str],
) -> None:
    payload = {
        "title": title,
        "date": schedule_date.isoformat(),
        "start_time": start_time.strftime("%H:%M"),
        "end_time": end_time.strftime("%H:%M"),
        "target_temperature": target_temperature,
        "precool_enabled": precool_enabled,
        "precool_minutes_before": precool_minutes_before,
        "repeat_enabled": repeat_enabled,
        "repeat_days": repeat_days,
    }
    if backend.put(f"/api/schedules/{schedule_id}", payload) is not None:
        return

    schedules = _load_schedules()
    schedule = next((s for s in schedules if s["id"] == schedule_id), None)
    if schedule is None:
        return
    schedule.update(
        title=title,
        date=schedule_date.isoformat(),
        start_time=start_time.strftime("%H:%M"),
        end_time=end_time.strftime("%H:%M"),
        target_temperature=target_temperature,
        precool_enabled=precool_enabled,
        precool_minutes_before=precool_minutes_before,
        repeat_enabled=repeat_enabled,
        repeat_days=repeat_days,
    )
    _save_schedules(schedules)


def delete_schedule(schedule_id: str) -> None:
    if backend.delete(f"/api/schedules/{schedule_id}") is not None:
        return
    schedules = [s for s in _load_schedules() if s["id"] != schedule_id]
    _save_schedules(schedules)


def repeat_days_label(schedule: dict) -> str:
    if not schedule["repeat_enabled"] or not schedule["repeat_days"]:
        return "없음"
    ordered = [d for d in _WEEKDAY_CODES if d in schedule["repeat_days"]]
    return "매주 " + "·".join(_WEEKDAY_LABELS[d] for d in ordered)


def _occurrence_datetimes(schedule: dict) -> tuple[datetime, datetime]:
    today = date.today()
    start = datetime.combine(today, time.fromisoformat(schedule["start_time"]))
    end = datetime.combine(today, time.fromisoformat(schedule["end_time"]))
    if end <= start:
        end += timedelta(days=1)
    return start, end


def schedule_status(schedule: dict) -> str:
    now = datetime.now()
    start, end = _occurrence_datetimes(schedule)
    if now > end:
        return "완료"
    if start <= now <= end:
        return "진행 중"
    return "예정"


def precool_info(schedule: dict) -> dict | None:
    if not schedule["precool_enabled"]:
        return None
    start, end = _occurrence_datetimes(schedule)
    precool_start = start - timedelta(minutes=schedule["precool_minutes_before"])
    expected_reach = precool_start + (start - precool_start) * 0.9
    now = datetime.now()
    active = precool_start <= now < start
    if now <= precool_start:
        progress = 0.0
    elif now >= start:
        progress = 1.0
    else:
        progress = (now - precool_start) / (start - precool_start)
    return {
        "active": active,
        "progress": max(0.0, min(1.0, progress)),
        "precool_start": precool_start,
        "expected_reach": expected_reach,
        "start": start,
    }


def active_progress(schedule: dict) -> dict | None:
    start, end = _occurrence_datetimes(schedule)
    now = datetime.now()
    if not (start <= now <= end):
        return None
    total_seconds = (end - start).total_seconds()
    elapsed_seconds = (now - start).total_seconds()
    progress = elapsed_seconds / total_seconds if total_seconds > 0 else 1.0
    return {
        "progress": max(0.0, min(1.0, progress)),
        "start": start,
        "end": end,
    }
