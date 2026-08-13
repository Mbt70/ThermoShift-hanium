import json
import uuid
from datetime import date, datetime
from pathlib import Path

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


def _with_catalog_fields(entry: dict) -> dict:
    catalog_entry = ERROR_CATALOG.get(entry["error_code"], {}) if entry["error_code"] else {}
    return {
        **entry,
        "failure_reason": catalog_entry.get("failure_reason"),
        "cause_guess": catalog_entry.get("cause_guess"),
        "checklist": catalog_entry.get("checklist", []),
    }


def list_logs(room_id: str, day: date, method: str | None = None) -> list[dict]:
    entries = _demo_entries(room_id, day) + [
        log for log in _load_recorded() if log["room_id"] == room_id
    ]
    entries = [entry for entry in entries if entry["timestamp"].date() == day]
    if method is not None:
        entries = [entry for entry in entries if entry["method"] == method]
    logs = [_with_catalog_fields(entry) for entry in entries]
    return sorted(logs, key=lambda log: log["timestamp"])


def get_log(log_id: str) -> dict | None:
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
