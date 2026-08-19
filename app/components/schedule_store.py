import sys
from datetime import date, datetime, time, timedelta
from pathlib import Path

_REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
if str(_REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPOSITORY_ROOT))

from app.components.api_client import api_delete, api_get, api_patch, api_post

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
# DB repeat_days is smallint[] using ISO weekday numbers (1=Mon..7=Sun).
_CODE_TO_DB_DAY = {code: i + 1 for i, code in enumerate(_WEEKDAY_CODES)}
_DB_DAY_TO_CODE = {i + 1: code for i, code in enumerate(_WEEKDAY_CODES)}

# Repeating schedules can't be open-ended in the DB (ck_sched_no_infinite),
# so a repeat with no explicit end date gets a long-but-bounded window.
_DEFAULT_REPEAT_WINDOW_DAYS = 180


def _from_api(row: dict) -> dict:
    repeat_days = [_DB_DAY_TO_CODE[d] for d in row.get("repeat_days") or [] if d in _DB_DAY_TO_CODE]
    precooling_min = row.get("precooling_min") or 0
    return {
        "id": row["schedule_id"],
        "room_id": row["room_id"],
        "title": row.get("title") or "",
        "date": row["valid_from"],
        "valid_until": row.get("valid_until"),
        "start_time": row["start_time"][:5],
        "end_time": row["end_time"][:5],
        "target_temperature": row["target_temp"],
        "precool_enabled": precooling_min > 0,
        "precool_minutes_before": precooling_min if precooling_min > 0 else 20,
        "repeat_enabled": bool(repeat_days),
        "repeat_days": repeat_days,
    }


def list_schedules(room_id: int) -> list[dict]:
    rows = api_get(f"/rooms/{room_id}/schedules") or []
    schedules = [_from_api(row) for row in rows]
    return sorted(schedules, key=lambda s: s["start_time"])


def list_today_schedules(room_id: int) -> list[dict]:
    today = date.today()
    today_code = _WEEKDAY_CODES[today.weekday()]
    schedules = []
    for schedule in list_schedules(room_id):
        valid_from = date.fromisoformat(schedule["date"])
        if schedule["repeat_enabled"]:
            valid_until = (
                date.fromisoformat(schedule["valid_until"]) if schedule["valid_until"] else None
            )
            in_window = valid_from <= today and (valid_until is None or today <= valid_until)
            if in_window and today_code in schedule["repeat_days"]:
                schedules.append(schedule)
        elif valid_from == today:
            schedules.append(schedule)
    return schedules


def get_schedule(schedule_id: int) -> dict | None:
    row = api_get(f"/schedules/{schedule_id}", ignore_404=True)
    return _from_api(row) if row else None


def _request_fields(
    *,
    title: str,
    schedule_date: date,
    start_time: time,
    end_time: time,
    target_temperature: int,
    precool_enabled: bool,
    precool_minutes_before: int,
    repeat_enabled: bool,
    repeat_days: list[str],
    created_by: int | None = None,
) -> dict:
    db_days = sorted(_CODE_TO_DB_DAY[code] for code in repeat_days if code in _CODE_TO_DB_DAY)
    valid_until = (
        (schedule_date + timedelta(days=_DEFAULT_REPEAT_WINDOW_DAYS)).isoformat()
        if repeat_enabled and db_days
        else None
    )
    return {
        "title": title or None,
        "valid_from": schedule_date.isoformat(),
        "valid_until": valid_until,
        "start_time": start_time.strftime("%H:%M"),
        "end_time": end_time.strftime("%H:%M"),
        "repeat_days": db_days if repeat_enabled else [],
        "target_temp": target_temperature,
        "precooling_min": precool_minutes_before if precool_enabled else 0,
        "created_by": created_by,
    }


def create_schedule(
    *,
    room_id: int,
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
    fields = _request_fields(
        title=title, schedule_date=schedule_date, start_time=start_time, end_time=end_time,
        target_temperature=target_temperature, precool_enabled=precool_enabled,
        precool_minutes_before=precool_minutes_before, repeat_enabled=repeat_enabled,
        repeat_days=repeat_days,
    )
    row = api_post(f"/rooms/{room_id}/schedules", json=fields)
    return _from_api(row)


def update_schedule(
    schedule_id: int,
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
    fields = _request_fields(
        title=title, schedule_date=schedule_date, start_time=start_time, end_time=end_time,
        target_temperature=target_temperature, precool_enabled=precool_enabled,
        precool_minutes_before=precool_minutes_before, repeat_enabled=repeat_enabled,
        repeat_days=repeat_days,
    )
    api_patch(f"/schedules/{schedule_id}", json=fields)


def delete_schedule(schedule_id: int) -> None:
    api_delete(f"/schedules/{schedule_id}", ignore_404=True)


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
