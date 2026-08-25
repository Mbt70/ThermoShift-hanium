"""Claude API 연동.

제어 판단 근거를 사람 말로 풀어주고, 알림 원인을 진단하고, 주간 리포트를
자동 생성한다. gateway가 남긴 reason_codes 같은 기계용 코드를 사용자와
심사위원이 읽을 수 있는 문장으로 바꾸는 것이 목적이다.

API 키가 없으면 모든 함수가 None 을 돌려주고, 호출부는 기존 하드코딩된
ERROR_CATALOG 로 폴백한다. 키 없이도 시스템 전체가 동작해야 한다.

키는 반드시 서버에만 둔다. 프론트(stlite)는 브라우저에서 돌기 때문에
거기에 키를 넣으면 그대로 노출된다.
"""

import logging
import os
from typing import Optional

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

# 기본 모델. 필요하면 THERMOSHIFT_AI_MODEL 로 바꾼다.
MODEL = os.environ.get("THERMOSHIFT_AI_MODEL", "claude-opus-5")


def _load_sdk():
    try:
        import anthropic  # noqa: PLC0415
        return anthropic
    except ImportError:
        return None


_anthropic = _load_sdk()
_client = None


def is_available() -> bool:
    """SDK와 자격증명이 모두 준비됐는지."""
    if _anthropic is None:
        return False
    return bool(os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN"))


def _get_client():
    global _client
    if _client is None:
        _client = _anthropic.Anthropic()
    return _client


# --------------------------------------------------------------------------
# 응답 스키마
# --------------------------------------------------------------------------

class DecisionExplanation(BaseModel):
    headline: str = Field(description="제어 판단을 한 문장으로 요약. 40자 이내")
    detail: str = Field(description="왜 그렇게 판단했는지 2~3문장. 센서 수치를 근거로 인용")
    recommendation: Optional[str] = Field(
        default=None, description="사용자가 취할 행동이 있으면 한 문장. 없으면 null"
    )


class AlertDiagnosis(BaseModel):
    failure_reason: str = Field(description="무슨 일이 일어났는지 한 문장")
    cause_guess: str = Field(description="가장 가능성 높은 원인 한 문장")
    checklist: list[str] = Field(description="사용자가 순서대로 확인할 항목 2~4개")


class WeeklyReport(BaseModel):
    summary: str = Field(description="이번 기간을 3~4문장으로 요약")
    highlights: list[str] = Field(description="잘 된 점 2~4개")
    concerns: list[str] = Field(description="문제가 된 점 2~4개")
    recommendations: list[str] = Field(description="다음 기간에 할 일 2~4개")


# --------------------------------------------------------------------------
# 공통 프롬프트
# --------------------------------------------------------------------------

_SYSTEM = """당신은 ThermoShift라는 실내 열환경 최적화 시스템의 분석 담당자입니다.
소규모 사무실·스터디룸에 설치된 센서와 에어컨 제어 로그를 해석해,
공간 관리자가 바로 이해할 수 있는 한국어로 설명합니다.

지켜야 할 것
- 주어진 데이터에 있는 사실만 말합니다. 없는 수치를 지어내지 않습니다.
- 수치를 인용할 때는 단위를 붙입니다 (26.5°C, 1340ppm).
- 전문 용어 대신 일상어를 씁니다. 'HMM 사후확률' 대신 '재실 추정'.
- 데이터가 부족하면 부족하다고 말합니다. 억지로 결론짓지 않습니다.
- 존댓말을 쓰되 간결하게 씁니다.

제어 모드 참고
- shadow: 판단만 하고 실제 에어컨 신호는 보내지 않는 관찰 모드입니다.
  이 모드에서 '전송되지 않음'은 고장이 아니라 의도된 동작입니다.
- active: 실제로 IR 신호를 보내 에어컨을 제어합니다."""


def _reason_code_glossary() -> str:
    """gateway가 쓰는 reason code 의 뜻. 모델이 코드를 오해하지 않게 붙인다."""
    return """reason code 의미
- ENV_STALE: 온습도/CO2 센서 데이터가 오래돼 판단 근거로 쓸 수 없음 (안전을 위해 현 상태 유지)
- MANUAL_LOCKOUT: 사람이 리모컨을 직접 조작해 자동 제어를 일시 차단한 상태
- OCCUPIED_CONFIRMED: 재실로 확정
- EMPTY_CONFIRMED: 공실로 확정
- TRANSITION_MAINTAIN_STATE: 재실/공실이 불확실해 현 상태 유지
- TEMPERATURE_HIGH_3MIN: 설정 임계보다 높은 온도가 3분 이상 지속
- TEMPERATURE_LOW_5MIN: 설정 임계보다 낮은 온도가 5분 이상 지속
- MIN_ON_TIME_SATISFIED / MIN_OFF_TIME_SATISFIED: 압축기 보호용 최소 가동/정지 시간 충족
- VENTILATE_RECOMMENDED: CO2가 경고 기준을 넘어 환기 권장
- CO2_CRITICAL: CO2가 위험 기준 초과
- SHADOW_MODE_NO_TRANSMIT: shadow 모드라 신호를 보내지 않음 (정상)
- LOCKOUT_NO_TRANSMIT: lockout 중이라 신호를 보내지 않음

decision_type 의미
- precool: 재실 예정 시각 전에 미리 냉방
- maintain: 목표 온도를 유지
- setback: 공실이라 설정을 완화
- ventilate: CO2가 높아 환기
- off: 냉방 정지

control_mode 의미 (DB 값)
- monitoring: 판단만 하고 신호를 보내지 않는 관찰 모드 (구 shadow)
- rule: 규칙 기반 자동 제어 (구 active)
- manual: 사람이 직접 내린 명령
- mpc: 예측 제어"""


def _call(prompt: str, schema, effort: str = "medium", max_tokens: int = 4000):
    """구조화 출력으로 한 번 호출한다. 실패하면 None."""
    if not is_available():
        return None
    try:
        response = _get_client().messages.parse(
            model=MODEL,
            max_tokens=max_tokens,
            system=_SYSTEM,
            thinking={"type": "adaptive"},
            output_config={"effort": effort},
            messages=[{"role": "user", "content": prompt}],
            output_format=schema,
        )
    except Exception:
        # AI는 부가 기능이다. 실패해도 본 기능이 멈추면 안 된다.
        logger.exception("Claude API 호출 실패")
        return None

    if response.stop_reason == "refusal":
        logger.warning("Claude가 응답을 거부했습니다: %s", response.stop_details)
        return None
    return response.parsed_output


# --------------------------------------------------------------------------
# 기능
# --------------------------------------------------------------------------

def explain_decision(decision: dict, room: dict) -> Optional[DecisionExplanation]:
    """제어 판단 한 건을 사람 말로 설명한다."""
    prompt = f"""아래는 ThermoShift가 내린 냉방 제어 판단 한 건입니다.
공간 관리자에게 왜 이렇게 판단했는지 설명해 주세요.

공간
- 이름: {room.get('name')}
- 목표 온도: {room.get('target_temp')}°C

판단
- 시각: {decision.get('decided_at')}
- 제어 모드: {decision.get('control_mode')}
- 판단 유형: {decision.get('decision_type')}
- 목표 온도: {decision.get('target_temp')}
- 재실 상태: {decision.get('occupancy_state')}
- 그때의 온도: {decision.get('temperature')}
- 그때의 CO2: {decision.get('co2')}
- 판단 근거: {decision.get('reason')}

{_reason_code_glossary()}"""
    return _call(prompt, DecisionExplanation, effort="low", max_tokens=2000)


def diagnose_alert(alert: dict, context: dict) -> Optional[AlertDiagnosis]:
    """알림 한 건의 원인을 추정하고 확인 절차를 만든다."""
    prompt = f"""아래 알림이 발생했습니다. 원인을 추정하고, 관리자가 순서대로
확인할 체크리스트를 만들어 주세요.

알림
- 분류: {alert.get('event_category')}
- 심각도: {alert.get('event_severity')}
- 처리 상태: {alert.get('status')}
- 내용: {alert.get('message')}
- 대상 디바이스: {alert.get('device_id') or '공간 전체'}
- 발생 시각: {alert.get('occurred_at')}

그때의 공간 상태
- 온도: {context.get('temperature')}
- 습도: {context.get('humidity')}
- CO2: {context.get('co2')}
- 센서 연결: {context.get('sensor_connected')}
- 마지막 센서 수신: {context.get('last_updated')}
- 최근 제어 판단: {context.get('recent_decision')}

설치된 장비: {context.get('devices')}"""
    return _call(prompt, AlertDiagnosis, effort="medium", max_tokens=2000)


def weekly_report(stats: dict) -> Optional[WeeklyReport]:
    """기간 KPI를 요약하고 다음 기간 할 일을 제안한다."""
    prompt = f"""아래는 ThermoShift 실증 공간의 기간별 집계입니다.
한이음 프로젝트 보고서에 넣을 수 있는 수준으로 요약해 주세요.

기간: {stats.get('start')} ~ {stats.get('end')}
공간: {stats.get('room_name')} (목표 온도 {stats.get('target_temp')}°C)

환경
- 온도: 평균 {stats.get('temp_avg')}°C / 최저 {stats.get('temp_min')}°C / 최고 {stats.get('temp_max')}°C
- 목표 범위(±2°C) 이탈 시간 비율: {stats.get('temp_out_of_range_pct')}%
- CO2: 평균 {stats.get('co2_avg')}ppm / 최고 {stats.get('co2_max')}ppm
- CO2 1000ppm 초과 시간 비율: {stats.get('co2_high_pct')}%

재실
- 재실로 판정된 시간 비율: {stats.get('occupied_pct')}%
- 재실 추정 표본 수: {stats.get('occupancy_samples')}

제어
- 제어 판단 횟수: {stats.get('decision_count')}
- 실제 전송된 명령: {stats.get('executed_count')}
- 제어 모드: {stats.get('control_modes')}
- 동작이 바뀐 횟수: {stats.get('action_changes')}
- 수동 명령: 성공 {stats.get('command_sent')} / 실패 {stats.get('command_failed')}

데이터 품질
- 센서 측정 건수: {stats.get('reading_count')}
- 품질 이상(INVALID) 비율: {stats.get('invalid_pct')}%
- 발생한 알림: {stats.get('alert_counts')}

주의: 전력 실측 장비(스마트 플러그)가 아직 설치되지 않아 에너지 사용량
데이터는 없습니다. 에너지 절감률을 추정하지 말고, 측정이 필요하다는 점을
concerns 에 적어 주세요."""
    return _call(prompt, WeeklyReport, effort="high", max_tokens=8000)
