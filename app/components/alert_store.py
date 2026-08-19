# Mock data only — no DB/API yet. Once a real alerts API exists, replace
# `_MOCK_ALERTS` (and the body of list_alerts/get_alert) with the API call;
# the rest of the app only depends on the dict shape returned here.

import json
from datetime import date, datetime
from pathlib import Path

from . import backend

_READ_STORE_PATH = Path(__file__).resolve().parents[2] / ".data" / "alert_reads.json"

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
    # not shown as filter chips yet, but already routable once real alerts arrive
    "humidity_abnormal": {
        "icon": "device_thermostat.svg",
        "filter_label": "습도 이탈",
        "severity": "warning",
    },
    "door_open": {"icon": "door.svg", "filter_label": "도어 열림", "severity": "warning"},
    "power_abnormal": {"icon": "plug.svg", "filter_label": "전력 이상", "severity": "critical"},
}

FILTER_OPTIONS = ["전체", "센서 오류", "CO₂ 초과", "온도 이탈", "제어 실패", "네트워크"]

_MOCK_ALERTS = [
    {
        "id": "1",
        "type": "sensor_offline",
        "room": "공학관 502",
        "device_id": "env_01",
        "title": "센서 노드 오프라인",
        "message": "env_01 신호 없음 → 제어 판단 불가",
        "time": "09:40",
        "status": "active",
    },
    {
        "id": "2",
        "type": "co2_high",
        "room": "공학관 502",
        "device_id": "env_01",
        "title": "CO₂ 농도 기준 초과",
        "message": "CO₂ 농도가 설정 기준을 초과했습니다.",
        "time": "09:25",
        "status": "active",
    },
    {
        "id": "3",
        "type": "temperature_abnormal",
        "room": "공학관 401",
        "device_id": "env_02",
        "title": "실내 온도 범위 이탈",
        "message": "실내 온도가 설정 범위를 벗어났습니다.",
        "time": "09:10",
        "status": "active",
    },
    {
        "id": "4",
        "type": "control_failed",
        "room": "공학관 502",
        "device_id": "ir_01",
        "title": "IR 명령 2회 실패",
        "message": "에어컨 응답 없음 → 수동 제어 필요",
        "time": "08:50",
        "status": "active",
    },
    {
        "id": "5",
        "type": "network_error",
        "room": "공학관 401",
        "device_id": None,
        "title": "네트워크 연결 오류",
        "message": (
            "장비와 서버 간 통신이 5분 이상 원활하지 않습니다. 게이트웨이 전원과 "
            "공유기 연결 상태를 확인한 뒤에도 반복되면 관리자에게 문의해 주세요."
        ),
        "time": "08:30",
        "status": "active",
    },
]


def _api_alerts(params: dict | None = None) -> list[dict] | None:
    """API 알림을 프론트 dict 형태로 변환한다.

    프론트는 시각을 'HH:MM' 문자열로, 공간을 이름 문자열로 기대한다.
    """
    remote = backend.get("/api/alerts", params or {"status": "active"})
    if remote is None:
        return None

    alerts = []
    for item in remote:
        created_at = item.get("created_at")
        timestamp = None
        if created_at:
            try:
                timestamp = datetime.fromisoformat(created_at).replace(tzinfo=None)
            except ValueError:
                timestamp = None
        alerts.append(
            {
                "id": item["id"],
                "room_id": item.get("room_id"),
                "room": item.get("room") or "-",
                "device_id": item.get("device_id"),
                "type": item["type"],
                "severity": item.get("severity", "warning"),
                "title": item["title"],
                "message": item.get("message") or "",
                "timestamp": timestamp,
                "time": timestamp.strftime("%H:%M") if timestamp else "",
                "status": item.get("status", "active"),
                "read": item.get("read", False),
            }
        )
    return alerts


def list_alerts(filter_label: str | None = None) -> list[dict]:
    alerts = _api_alerts()
    if alerts is None:
        alerts = list(_MOCK_ALERTS)
    if filter_label and filter_label != "전체":
        alert_type = next(
            (t for t, cfg in ALERT_TYPE_CONFIG.items() if cfg["filter_label"] == filter_label),
            None,
        )
        alerts = [alert for alert in alerts if alert["type"] == alert_type]
    return alerts


def get_alert(alert_id: str) -> dict | None:
    alerts = _api_alerts({"status": "all"})
    if alerts is not None:
        return next((alert for alert in alerts if alert["id"] == alert_id), None)
    return next((alert for alert in _MOCK_ALERTS if alert["id"] == alert_id), None)


def active_alert_count() -> int:
    summary = backend.get("/api/alerts/summary")
    if summary is not None:
        return summary.get("active", 0)
    return sum(1 for alert in _MOCK_ALERTS if alert["status"] == "active")


def alert_severity_counts() -> dict:
    summary = backend.get("/api/alerts/summary")
    if summary is not None:
        return {
            "critical": summary.get("critical", 0),
            "warning": summary.get("warning", 0),
        }

    counts = {"critical": 0, "warning": 0}
    for alert in _MOCK_ALERTS:
        if alert["status"] != "active":
            continue
        severity = ALERT_TYPE_CONFIG.get(alert["type"], {}).get("severity", "warning")
        counts[severity] += 1
    return counts


# ---- per-room, per-day alerts (web 대시보드 알림 페이지) ----
# Rooms are user-registered (no fixed demo IDs), so - same approach as
# control_log_store's _DEMO_TEMPLATE - this generates mock alerts for
# whichever room is asked for, rather than pulling from the fixed
# _MOCK_ALERTS list above (which predates per-room/per-day scoping and
# still backs the older mobile alert list/list_alerts API).
#
# Only shown for *today* - a freshly registered room has no alert history,
# so every other date is legitimately empty rather than replaying the same
# demo alerts on every day like control_log_store's demo template does.
_ROOM_DEMO_TEMPLATE = [
    (13, 0, "control_failed", "에어컨 동작 미확인"),
    (9, 25, "co2_high", "CO2 농도 초과"),
]


def _load_read_ids() -> set[str]:
    if not _READ_STORE_PATH.exists():
        return set()
    return set(json.loads(_READ_STORE_PATH.read_text(encoding="utf-8")))


def _save_read_ids(ids: set[str]) -> None:
    _READ_STORE_PATH.parent.mkdir(parents=True, exist_ok=True)
    _READ_STORE_PATH.write_text(
        json.dumps(sorted(ids), ensure_ascii=False, indent=2), encoding="utf-8"
    )


def mark_alert_read(alert_id: str) -> None:
    if backend.post(f"/api/alerts/{alert_id}/read") is not None:
        return

    ids = _load_read_ids()
    if alert_id not in ids:
        ids.add(alert_id)
        _save_read_ids(ids)


def _room_demo_entry(room_id: str, day: date, entry: tuple, read_ids: set[str]) -> dict:
    hour, minute, alert_type, title = entry
    timestamp = datetime.combine(day, datetime.min.time()).replace(hour=hour, minute=minute)
    config = ALERT_TYPE_CONFIG.get(alert_type, {})
    alert_id = f"{room_id}_{day.isoformat()}_{hour:02d}{minute:02d}"
    return {
        "id": alert_id,
        "room_id": room_id,
        "timestamp": timestamp,
        "type": alert_type,
        "title": title,
        "severity": config.get("severity", "warning"),
        "read": alert_id in read_ids,
    }


def list_room_alerts(room_id: str, day: date) -> list[dict]:
    remote = _api_alerts({"room_id": room_id, "status": "all"})
    if remote is not None:
        same_day = [
            alert for alert in remote
            if alert["timestamp"] is not None and alert["timestamp"].date() == day
        ]
        return sorted(same_day, key=lambda alert: alert["timestamp"])

    if day != date.today():
        return []
    read_ids = _load_read_ids()
    entries = [_room_demo_entry(room_id, day, entry, read_ids) for entry in _ROOM_DEMO_TEMPLATE]
    return sorted(entries, key=lambda alert: alert["timestamp"])
