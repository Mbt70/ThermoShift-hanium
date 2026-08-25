"""AI 분석 결과를 가져오는 store.

Claude API 키는 서버에만 있다. 프론트는 결과만 받아간다.
AI가 꺼져 있으면 모든 함수가 None 을 돌려주고, 호출부는 기존
하드코딩된 설명(ERROR_CATALOG)으로 폴백한다.

주의: 목록 화면에서는 호출하지 않는다. 항목마다 API를 부르면 느리고
비용도 커진다. 상세 화면처럼 사용자가 명시적으로 연 곳에서만 부른다.
"""

from datetime import date
from typing import Optional

from . import backend


def is_available() -> bool:
    status = backend.get("/api/ai/status")
    return bool(status and status.get("available"))


def explain_decision(log_id: str) -> Optional[dict]:
    """자동 제어 판단 한 건의 근거 설명. {headline, detail, recommendation}"""
    if not log_id.startswith("decision:"):
        return None
    return backend.post("/api/ai/explain-decision", params={"log_id": log_id})


def diagnose_alert(alert_id: str) -> Optional[dict]:
    """알림 원인 진단. {failure_reason, cause_guess, checklist}"""
    return backend.post("/api/ai/diagnose-alert", params={"alert_id": alert_id})


def period_stats(room_id: str, start: date, end: date) -> Optional[dict]:
    """AI 없이 KPI 숫자만. 성과 리포트 화면이 쓴다."""
    return backend.get(
        "/api/ai/stats",
        {"room_id": room_id, "start": start.isoformat(), "end": end.isoformat()},
    )


def report(room_id: str, start: date, end: date) -> Optional[dict]:
    """KPI 집계 + AI 요약. {stats, ai, ai_unavailable_reason}

    AI가 꺼져 있어도 stats 는 채워져 돌아온다.
    """
    return backend.post(
        "/api/ai/report",
        params={"room_id": room_id, "start": start.isoformat(), "end": end.isoformat()},
    )
