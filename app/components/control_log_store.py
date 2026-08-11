from datetime import date, datetime

_METHOD_LABELS = {"rule": "규칙", "manual": "수동", "predict": "예측"}

_TEMPLATE = [
    (8, 0, "rule", "에어컨 켜기 · 냉방", True, None, None, []),
    (
        13,
        0,
        "rule",
        "에어컨 동작 미확인",
        False,
        "IR 명령은 전송됐지만 전력 변화가 감지되지 않았습니다.",
        "에어컨 전원이 꺼져 있거나, IR 송신기 방향이 맞지 않을 수 있습니다.",
        ["에어컨 전원 상태 확인", "IR 송신기 앞 장애물 확인", "스마트플러그 연결 상태 확인"],
    ),
    (13, 5, "rule", "설정 온도 24°C", True, None, None, []),
    (15, 30, "predict", "재실 감지 선냉방", True, None, None, []),
    (15, 32, "rule", "IR 재시도 후 성공", True, None, None, []),
    (18, 0, "manual", "에어컨 끄기", True, None, None, []),
    (
        19,
        10,
        "predict",
        "반복 제어 실패",
        False,
        "IR 신호를 3회 재전송했지만 센서 응답이 없습니다.",
        "센서 배터리가 방전됐거나 게이트웨이와의 통신 범위를 벗어났을 수 있습니다.",
        ["센서 배터리 잔량 확인", "센서-게이트웨이 거리 확인", "게이트웨이 재부팅"],
    ),
]


def _build_log(room_id: str, day: date, entry: tuple) -> dict:
    hour, minute, method, content, success, failure_reason, cause_guess, checklist = entry
    return {
        "id": f"{room_id}_{day.isoformat()}_{hour:02d}{minute:02d}",
        "room_id": room_id,
        "timestamp": datetime.combine(day, datetime.min.time()).replace(
            hour=hour, minute=minute
        ),
        "method": method,
        "content": content,
        "success": success,
        "failure_reason": failure_reason,
        "cause_guess": cause_guess,
        "checklist": checklist,
    }


def list_logs(room_id: str, day: date, method: str | None = None) -> list[dict]:
    logs = [
        _build_log(room_id, day, entry)
        for entry in _TEMPLATE
        if method is None or entry[2] == method
    ]
    return sorted(logs, key=lambda log: log["timestamp"])


def get_log(log_id: str) -> dict | None:
    room_id, day_str, _ = log_id.rsplit("_", 2)
    try:
        day = date.fromisoformat(day_str)
    except ValueError:
        return None
    return next((log for log in list_logs(room_id, day) if log["id"] == log_id), None)


def method_label(method: str) -> str:
    return _METHOD_LABELS.get(method, method)
