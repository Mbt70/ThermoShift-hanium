import json
import uuid
from datetime import date, datetime
from pathlib import Path

from . import ai_store, backend

_STORE_PATH = Path(__file__).resolve().parents[2] / ".data" / "control_logs.json"

_METHOD_LABELS = {"rule": "규칙", "manual": "수동", "predict": "예측"}

ERROR_CATALOG = {
    "command_failed": {
        "failure_reason": "IR 신호 전송에 실패했습니다.",
        "cause_guess": "IR 송신 모듈 전원이 꺼져 있거나 배터리가 부족할 수 있습니다.",
        "checklist": ["IR 송신 모듈 전원 확인", "배터리 잔량 확인", "기기와의 거리 확인"],
    },
    "no_power_change": {
        "failure_reason": "IR 명령은 전송됐지만 전력 변화가 감지되지 않았습니다.",
        "cause_guess": "에어컨 전원이 꺼져 있거나, IR 송신기 방향이 맞지 않을 수 있습니다.",
        "checklist": ["에어컨 전원 상태 확인", "IR 송신기 앞 장애물 확인", "스마트플러그 연결 상태 확인"],
    },
    "no_sensor_response": {
        "failure_reason": "IR 신호를 3회 재전송했지만 센서 응답이 없습니다.",
        "cause_guess": "센서 배터리가 방전됐거나 게이트웨이와의 통신 범위를 벗어났을 수 있습니다.",
        "checklist": ["센서 배터리 잔량 확인", "센서-게이트웨이 거리 확인", "게이트웨이 재부팅"],
    },
    "unknown": {
        "failure_reason": "원인을 알 수 없는 오류가 발생했습니다.",
        "cause_guess": "일시적인 통신 오류일 수 있습니다. 잠시 후 다시 시도해 주세요.",
        "checklist": ["잠시 후 다시 시도", "기기 전원 재연결", "그래도 반복되면 관리자에게 문의"],
    },
    # non-control system events (알림에서 넘어오는 것들). 제어 명령이 아니라
    # 센서/환경/네트워크 상태 이벤트지만, 사용자에게 보여주는 방식은 제어
    # 실패와 동일하므로 같은 카탈로그에서 관리한다.
    "sensor_offline": {
        "failure_reason": "센서 노드에서 3분 이상 신호가 수신되지 않았습니다.",
        "cause_guess": "센서 배터리가 방전됐거나 게이트웨이와의 통신 범위를 벗어났을 수 있습니다.",
        "checklist": ["센서 배터리 잔량 확인", "센서-게이트웨이 거리 확인", "게이트웨이 재부팅"],
    },
    "co2_high": {
        "failure_reason": "CO₂ 농도가 설정 기준을 초과했습니다.",
        "cause_guess": "환기가 원활하지 않거나 재실 인원이 많아 농도가 상승했을 수 있습니다.",
        "checklist": ["환기 장치 동작 확인", "창문 개방 여부 확인", "재실 인원 확인"],
    },
    "temperature_abnormal": {
        "failure_reason": "실내 온도가 설정 범위를 벗어났습니다.",
        "cause_guess": "냉난방 기기가 정상 동작하지 않거나 외부 온도 영향을 받았을 수 있습니다.",
        "checklist": ["냉난방 기기 동작 확인", "설정 온도 확인", "창문/문 개방 여부 확인"],
    },
    "network_error": {
        "failure_reason": "장비와 서버 간 통신이 5분 이상 원활하지 않습니다.",
        "cause_guess": "게이트웨이 전원이 꺼졌거나 공유기 연결이 끊겼을 수 있습니다.",
        "checklist": ["게이트웨이 전원 확인", "공유기 연결 상태 확인", "그래도 반복되면 관리자에게 문의"],
    },
}

_DEMO_TEMPLATE = [
    (8, 0, "rule", "에어컨 켜기 · 냉방", True, None, None),
    (9, 15, "manual", "온도 설정", False, "온도 설정 명령이 실패했어요", "command_failed"),
    (13, 0, "rule", "에어컨 동작", False, "에어컨 동작이 확인되지 않았어요", "no_power_change"),
    (13, 5, "rule", "설정 온도 24°C", True, None, None),
    (14, 40, "rule", "예약 냉방 실행", True, None, None),
    (15, 30, "predict", "재실 감지 선냉방", True, None, None),
    (15, 32, "rule", "IR 재시도 후 성공", True, None, None),
    (18, 0, "manual", "에어컨 끄기", True, None, None),
    (19, 10, "predict", "반복 제어", False, "반복 제어 명령이 전송되지 않았어요", "no_sensor_response"),
]


def _demo_entry(room_id: str, day: date, entry: tuple) -> dict:
    hour, minute, method, content, success, failure_title, error_code = entry
    timestamp = datetime.combine(day, datetime.min.time()).replace(hour=hour, minute=minute)
    return {
        "id": f"{room_id}_{day.isoformat()}_{hour:02d}{minute:02d}",
        "room_id": room_id,
        "timestamp": timestamp,
        "method": method,
        "content": content,
        "success": success,
        "failure_title": failure_title,
        "error_code": error_code,
    }


def _demo_entries(room_id: str, day: date) -> list[dict]:
    return [_demo_entry(room_id, day, entry) for entry in _DEMO_TEMPLATE]


def _load_recorded() -> list[dict]:
    if not _STORE_PATH.exists():
        return []
    logs = json.loads(_STORE_PATH.read_text(encoding="utf-8"))
    for log in logs:
        log["timestamp"] = datetime.fromisoformat(log["timestamp"])
    return logs


def _save_recorded(logs: list[dict]) -> None:
    _STORE_PATH.parent.mkdir(parents=True, exist_ok=True)
    serializable = [{**log, "timestamp": log["timestamp"].isoformat()} for log in logs]
    _STORE_PATH.write_text(
        json.dumps(serializable, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def record_log(
    *,
    room_id: str,
    method: str,
    content: str,
    success: bool,
    failure_title: str | None = None,
    error_code: str | None = None,
) -> dict:
    created = backend.post(
        "/api/control/commands",
        json={"action": content, "method": method},
        params={"room_id": room_id},
    )
    if created is not None:
        return {
            "id": f"command:{created['id']}",
            "room_id": room_id,
            "timestamp": datetime.now(),
            "method": method,
            "content": content,
            "success": success,
            "failure_title": failure_title,
            "error_code": error_code if not success else None,
        }

    logs = _load_recorded()
    entry = {
        "id": uuid.uuid4().hex,
        "room_id": room_id,
        "timestamp": datetime.now(),
        "method": method,
        "content": content,
        "success": success,
        "failure_title": failure_title,
        "error_code": error_code if not success else None,
    }
    logs.append(entry)
    _save_recorded(logs)
    return entry


def _from_api(entry: dict) -> dict:
    """API 로그 응답을 프론트가 쓰던 dict 형태로 맞춘다.

    가장 중요한 차이는 timestamp 다. 페이지들은 datetime 객체를 기대하는데
    API는 ISO 문자열(로컬 시간대)을 준다.
    """
    timestamp = entry.get("timestamp")
    if isinstance(timestamp, str):
        try:
            parsed = datetime.fromisoformat(timestamp)
            # 이후 비교/표시는 모두 로컬 naive 기준이라 tz 정보를 떼어낸다.
            timestamp = parsed.replace(tzinfo=None)
        except ValueError:
            timestamp = None
    return {
        "id": entry["id"],
        "room_id": entry.get("room_id"),
        "timestamp": timestamp,
        "method": entry.get("method"),
        "content": entry.get("content"),
        "success": entry.get("success", True),
        "failure_title": entry.get("failure_title"),
        "error_code": entry.get("error_code"),
        # API에만 있는 부가 정보. 상세 화면에서 제어 근거를 보여줄 때 쓴다.
        "reason_codes": entry.get("reason_codes", []),
        "simulated": entry.get("simulated", False),
        "control_mode": entry.get("control_mode"),
        "occupancy_state": entry.get("occupancy_state"),
        "temperature": entry.get("temperature"),
        "co2": entry.get("co2"),
    }


def _with_catalog_fields(entry: dict) -> dict:
    catalog_entry = ERROR_CATALOG.get(entry["error_code"], {}) if entry["error_code"] else {}
    return {
        **entry,
        "failure_reason": catalog_entry.get("failure_reason"),
        "cause_guess": catalog_entry.get("cause_guess"),
        "checklist": catalog_entry.get("checklist", []),
    }


def list_logs(room_id: str, day: date, method: str | None = None) -> list[dict]:
    remote = backend.get(
        "/api/control/logs",
        {"room_id": room_id, "date": day.isoformat(), **({"method": method} if method else {})},
    )
    if remote is not None:
        logs = [_with_catalog_fields(_from_api(entry)) for entry in remote]
        return sorted(logs, key=lambda log: log["timestamp"] or datetime.min)

    entries = _demo_entries(room_id, day) + [
        log for log in _load_recorded() if log["room_id"] == room_id
    ]
    entries = [entry for entry in entries if entry["timestamp"].date() == day]
    if method is not None:
        entries = [entry for entry in entries if entry["method"] == method]
    logs = [_with_catalog_fields(entry) for entry in entries]
    return sorted(logs, key=lambda log: log["timestamp"])


def _alert_as_log(alert_id: str) -> dict | None:
    # Bridge for 알림 → 제어로그 상세 unification: sensor/env/network alerts
    # aren't control commands, so they don't live in _DEMO_TEMPLATE — this
    # builds a log-shaped dict from the alert on the fly instead.
    from app.components.alert_store import get_alert

    alert = get_alert(alert_id)
    if alert is None:
        return None
    entry = _with_catalog_fields(
        {
            "id": f"alert_{alert_id}",
            "room_id": alert.get("room_id"),
            "timestamp": alert.get("timestamp"),
            "method": None,
            "content": alert["title"],
            "success": False,
            "failure_title": alert["title"],
            "error_code": alert["type"],
        }
    )
    # AI가 켜져 있으면 카탈로그의 일반론 대신 실제 상황에 맞춘 진단으로 덮어쓴다.
    diagnosis = ai_store.diagnose_alert(alert_id)
    if diagnosis:
        entry.update(
            {
                "failure_reason": diagnosis.get("failure_reason") or entry["failure_reason"],
                "cause_guess": diagnosis.get("cause_guess") or entry["cause_guess"],
                "checklist": diagnosis.get("checklist") or entry["checklist"],
                "ai_generated": True,
            }
        )
    return entry


def get_log(log_id: str) -> dict | None:
    if log_id.startswith("alert_"):
        return _alert_as_log(log_id[len("alert_") :])
    if log_id.startswith(("decision:", "command:")):
        remote = backend.get(f"/api/control/logs/{log_id}")
        if not remote:
            return None
        entry = _with_catalog_fields(_from_api(remote))
        # 자동 판단은 reason_codes 가 기계용 코드라 그대로는 읽기 어렵다.
        # AI가 켜져 있으면 사람 말로 풀어 붙인다. 꺼져 있으면 None.
        entry["explanation"] = ai_store.explain_decision(log_id)
        return entry
    recorded = next((log for log in _load_recorded() if log["id"] == log_id), None)
    if recorded is not None:
        return _with_catalog_fields(recorded)
    try:
        room_id, day_str, _ = log_id.rsplit("_", 2)
        day = date.fromisoformat(day_str)
    except ValueError:
        return None
    demo = next((e for e in _demo_entries(room_id, day) if e["id"] == log_id), None)
    return _with_catalog_fields(demo) if demo else None


def method_label(method: str) -> str:
    return _METHOD_LABELS.get(method, method)
