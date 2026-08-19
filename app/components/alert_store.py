import sys
from datetime import date, datetime
from pathlib import Path

_REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
if str(_REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPOSITORY_ROOT))

from app.components.api_client import api_get, api_patch

# Kept only for the legacy mobile pages (app/pages/alert.py, log_list.py)
# that still import these - the web app no longer reads them (severity/
# labels now come straight from the DB's event_category/event_severity).
ALERT_TYPE_CONFIG = {
    "sensor_offline": {"icon": "sensors.svg", "filter_label": "센서 오류", "severity": "critical"},
    "co2_high": {"icon": "control_error.svg", "filter_label": "CO₂ 초과", "severity": "warning"},
    "temperature_abnormal": {
        "icon": "device_thermostat.svg",
        "filter_label": "온도 이탈",
        "severity": "warning",
    },
    "control_failed": {
        "icon": "settings_remote.svg",
        "filter_label": "제어 실패",
        "severity": "critical",
    },
    "network_error": {"icon": "control_error.svg", "filter_label": "네트워크", "severity": "critical"},
    "humidity_abnormal": {
        "icon": "device_thermostat.svg",
        "filter_label": "습도 이탈",
        "severity": "warning",
    },
    "door_open": {"icon": "door.svg", "filter_label": "도어 열림", "severity": "warning"},
    "power_abnormal": {"icon": "plug.svg", "filter_label": "전력 이상", "severity": "critical"},
}

FILTER_OPTIONS = ["전체", "센서 오류", "CO₂ 초과", "온도 이탈", "제어 실패", "네트워크"]

_SEVERITY_MAP = {"critical": "critical", "warning": "warning", "info": "warning"}


def _from_api(row: dict) -> dict:
    return {
        "id": row["event_id"],
        "room_id": row["room_id"],
        "timestamp": datetime.fromisoformat(row["occurred_at"]),
        "type": row["event_category"],
        "title": row.get("message") or row["event_category"],
        "severity": _SEVERITY_MAP.get(row["event_severity"], "warning"),
        "read": row["status"] != "open",
    }


def list_room_alerts(room_id: int, day: date) -> list[dict]:
    rows = api_get(f"/rooms/{room_id}/events", params={"day": day.isoformat()}) or []
    alerts = [_from_api(row) for row in rows]
    return sorted(alerts, key=lambda alert: alert["timestamp"])


def mark_alert_read(alert_id: int) -> None:
    api_patch(f"/events/{alert_id}/read")


def get_alert(event_id) -> dict | None:
    row = api_get(f"/events/{event_id}", ignore_404=True)
    return _from_api(row) if row else None


def alert_severity_counts(room_ids: list[int] | None = None) -> dict:
    counts = {"critical": 0, "warning": 0}
    for room_id in room_ids or []:
        rows = api_get(f"/rooms/{room_id}/events") or []
        for row in rows:
            if row["status"] != "open":
                continue
            counts[_SEVERITY_MAP.get(row["event_severity"], "warning")] += 1
    return counts


def active_alert_count(room_ids: list[int] | None = None) -> int:
    counts = alert_severity_counts(room_ids)
    return counts["critical"] + counts["warning"]


def list_alerts(filter_label: str | None = None) -> list[dict]:
    # Legacy mobile-only entry point (app/pages/alert.py) - it had no
    # concept of "which room/user" and just listed a fixed global mock
    # list, which doesn't map onto the real multi-tenant schema. Kept as a
    # no-op stub so that page's import doesn't crash outright.
    return []
