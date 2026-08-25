import sys
from datetime import date, datetime
from pathlib import Path

_REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
if str(_REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPOSITORY_ROOT))

from shared.api_client import api_get

_METHOD_LABELS = {"rule": "규칙", "manual": "수동", "predict": "예측"}

# UI method codes vs the DB's control_mode enum - "predict" here (not
# digital_twin.py's "predictive") matches the icon/label map this page has
# always used; "mpc" is the DB's spelling of the same mode either way.
_METHOD_DB_TO_UI = {"mpc": "predict"}
_METHOD_UI_TO_DB = {"predict": "mpc"}

_COMMAND_LABELS = {
    "power_on": "에어컨 켜기",
    "power_off": "에어컨 끄기",
    "set_temp": "온도 설정",
    "set_mode": "모드 변경",
    "set_fan": "풍량 설정",
}


def method_label(method: str) -> str:
    return _METHOD_LABELS.get(method, method)


def _content_label(row: dict) -> str:
    base = _COMMAND_LABELS.get(row["command_type"], row["command_type"])
    if row["command_type"] == "set_temp" and row.get("target_temp") is not None:
        return f"{base} {row['target_temp']:.0f}°C"
    return base


def _checklist(action_guide: str | None) -> list[str]:
    if not action_guide:
        return []
    if "\n" in action_guide:
        return [line.strip() for line in action_guide.splitlines() if line.strip()]
    return [action_guide]


# event_severity ('critical'/'warning', already collapsed from the DB's
# info/warning/critical via alert_store's _SEVERITY_MAP) -> this page's
# status tier. Kept separate from "fail" (an actual failed control command)
# so 위험/주의 events and 실패 commands can be filtered independently.
_EVENT_SEVERITY_STATUS = {"critical": "danger", "warning": "warning"}


def _from_api(row: dict) -> dict:
    success = row["command_status"] == "acked"
    return {
        "id": row["command_id"],
        "room_id": row["room_id"],
        "timestamp": datetime.fromisoformat(row["issued_at"]),
        "method": _METHOD_DB_TO_UI.get(row["control_mode"], row["control_mode"]),
        "content": _content_label(row),
        "success": success,
        "status": "success" if success else "fail",
        "failure_title": None if success else row.get("result_message"),
        "error_code": None,
        "failure_reason": None if success else row.get("result_message"),
        "cause_guess": None if success else row.get("estimated_cause"),
        "checklist": [] if success else _checklist(row.get("action_guide")),
    }


def _event_as_log(alert: dict) -> dict:
    # Shapes an event_logs row (already alert_store-mapped) as a log-row
    # dict, so 제어목록 can show 기준 초과 등 이벤트 alongside 제어 명령 이력.
    return {
        "id": f"alert_{alert['id']}",
        "room_id": alert.get("room_id"),
        "timestamp": alert.get("timestamp"),
        "method": None,
        "content": alert["title"],
        "success": False,
        "status": _EVENT_SEVERITY_STATUS.get(alert["severity"], "warning"),
        "failure_title": alert["title"],
        "error_code": alert.get("type"),
        "failure_reason": alert["title"],
        "cause_guess": alert.get("cause_guess"),
        "checklist": alert.get("checklist", []),
    }


def list_logs(room_id: int, day: date, method: str | None = None) -> list[dict]:
    from app.components.alert_store import list_room_alerts

    rows = api_get(f"/rooms/{room_id}/commands", params={"day": day.isoformat()}) or []
    logs = [_from_api(row) for row in rows]
    logs += [_event_as_log(alert) for alert in list_room_alerts(room_id, day)]
    if method is not None:
        logs = [log for log in logs if log["method"] == method]
    return sorted(logs, key=lambda log: log["timestamp"])


def _alert_as_log(alert_id: str) -> dict | None:
    # Bridge for 알림 → 제어로그 상세 unification: sensor/env/network alerts
    # aren't control commands, so they're built as a log-shaped dict on the
    # fly from the event instead.
    from app.components.alert_store import get_alert

    alert = get_alert(alert_id)
    return _event_as_log(alert) if alert else None


def get_log(log_id) -> dict | None:
    if isinstance(log_id, str) and log_id.startswith("alert_"):
        return _alert_as_log(log_id[len("alert_") :])
    row = api_get(f"/commands/{log_id}", ignore_404=True)
    return _from_api(row) if row else None
