# Mock data only — no DB/API yet. Once a real alerts API exists, replace
# `_MOCK_ALERTS` (and the body of list_alerts/get_alert) with the API call;
# the rest of the app only depends on the dict shape returned here.

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


def list_alerts(filter_label: str | None = None) -> list[dict]:
    alerts = list(_MOCK_ALERTS)
    if filter_label and filter_label != "전체":
        alert_type = next(
            (t for t, cfg in ALERT_TYPE_CONFIG.items() if cfg["filter_label"] == filter_label),
            None,
        )
        alerts = [alert for alert in alerts if alert["type"] == alert_type]
    return alerts


def get_alert(alert_id: str) -> dict | None:
    return next((alert for alert in _MOCK_ALERTS if alert["id"] == alert_id), None)


def active_alert_count() -> int:
    return sum(1 for alert in _MOCK_ALERTS if alert["status"] == "active")


def alert_severity_counts() -> dict:
    counts = {"critical": 0, "warning": 0}
    for alert in _MOCK_ALERTS:
        if alert["status"] != "active":
            continue
        severity = ALERT_TYPE_CONFIG.get(alert["type"], {}).get("severity", "warning")
        counts[severity] += 1
    return counts
