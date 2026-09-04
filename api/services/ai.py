"""Gemini API 연동.

제어 판단 근거를 사람 말로 풀어주고, 알림 원인을 진단하고, 주간 리포트를
자동 생성한다. gateway(policy.py)가 남긴 판단 근거는 이미 한국어 문장이지만
여러 줄 쌓인 채로 관측값(temp=/co2= 등)이 뒤섞여 있어, 이를 관리자와
심사위원이 한눈에 읽을 수 있는 한두 문장 요약·설명으로 다듬는 것이 목적이다.

API 키가 없으면 모든 함수가 None 을 돌려주고, 호출부는 기존 하드코딩된
ERROR_CATALOG 로 폴백한다. 키 없이도 시스템 전체가 동작해야 한다.

키는 반드시 서버에만 둔다. 프론트(stlite)는 브라우저에서 돌기 때문에
거기에 키를 넣으면 그대로 노출된다.
"""

import logging
import os
import json
from typing import Optional

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

# 기본 모델. 필요하면 THERMOSHIFT_AI_MODEL 로 바꾼다.
MODEL = os.environ.get("THERMOSHIFT_AI_MODEL", "gemini-flash-lite-latest")

# effort 단계별 thinking 토큰 예산. "low"는 지연시간이 중요한 즉시 설명용,
# "high"는 주간 리포트처럼 한 번에 길게 종합하는 작업용.
_THINKING_BUDGET = {"low": 1024, "medium": 4096, "high": 8192}


def _load_sdk():
    try:
        from google import genai  # noqa: PLC0415
        return genai
    except ImportError:
        return None


_genai = _load_sdk()
_client = None


def is_available() -> bool:
    """SDK와 자격증명이 모두 준비됐는지."""
    if _genai is None:
        return False
    return bool(os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY"))


def _get_client():
    global _client
    if _client is None:
        _client = _genai.Client(api_key=os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY"))
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


class CopilotToolPlan(BaseModel):
    tool_name: str = Field(description="허용된 도구 이름 하나")
    arguments: dict = Field(default_factory=dict, description="도구에 전달할 구조화 인자")
    reason: str = Field(description="이 도구를 고른 이유 한 문장")


class _GeminiCopilotToolPlan(BaseModel):
    """Gemini Developer API가 지원하는 고정 속성 응답 스키마.

    자유 형식 dict는 JSON Schema의 additionalProperties를 만들고 Developer
    API가 이를 거절한다. 모델에는 가능한 인자를 명시적으로 펼친 스키마를
    주고, 받은 뒤 내부 CopilotToolPlan.arguments로 다시 묶는다.
    """

    tool_name: str = Field(description="허용된 도구 이름 하나")
    selection_reason: str = Field(description="이 도구를 고른 이유 한 문장")
    limit: Optional[int] = None
    run_id: Optional[int] = None
    temperature_c: Optional[float] = None
    humidity_pct: Optional[float] = None
    p_occupied: Optional[float] = None
    current_cooling_on: Optional[bool] = None
    command_type: Optional[str] = None
    target_temp: Optional[float] = None
    plan_key: Optional[str] = None


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
    """gateway(policy.py)가 남기는 판단 근거의 형식. 모델이 오해하지 않게 붙인다."""
    return """판단 근거(reason) 형식
gateway의 policy.py가 우선순위대로 판단하며, 판단할 때마다 근거 문장을
쌓는다(예: "예약 진행 중 (목표 24.0℃)", "재실 중 · 실내 26.8℃ (쾌적
23.0~25.0℃)", "CO2 1520ppm — 위험 기준(1500) 초과, 즉시 환기 필요").
그 뒤에 " | " 로 구분해 판단 시점의 관측값이 영문 key=value 로 붙는다
(temp=, co2=, occupancy=, executed=). 이 관측값은 코드가 아니라 그대로
읽으면 되는 실측치다.

우선순위(위에서부터 먼저 걸리는 조건이 그 판단으로 확정): 안전(센서
끊김) → 수동 잠금(사람이 리모컨으로 직접 조작 중) → CO2 위험/경고 →
예약 예냉(열모델이 리드타임 계산) → 공실 → 재실 중 온도.
"열모델 미교정(가정값)" 문구가 보이면 선냉방 리드타임이 아직 실측
보정 전 추정치라는 뜻 — 있는 그대로 전달하고 확정적으로 말하지 않는다.

decision_type 의미
- precool: 재실 예정 시각 전에 미리 냉방
- maintain: 목표 온도를 유지
- setback: 쾌적 허용대역 안이어서 냉방을 쉬거나, 공실이라 설정을 완화
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
        from google.genai import types  # noqa: PLC0415

        response = _get_client().models.generate_content(
            model=MODEL,
            contents=prompt,
            config=types.GenerateContentConfig(
                system_instruction=_SYSTEM,
                max_output_tokens=max_tokens,
                response_mime_type="application/json",
                response_schema=schema,
                thinking_config=types.ThinkingConfig(
                    thinking_budget=_THINKING_BUDGET.get(effort, 4096)
                ),
            ),
        )
    except Exception:
        # AI는 부가 기능이다. 실패해도 본 기능이 멈추면 안 된다.
        logger.exception("Gemini API 호출 실패")
        return None

    candidates = response.candidates or []
    if not candidates or candidates[0].finish_reason not in ("STOP", None):
        logger.warning("Gemini가 응답을 완료하지 못했습니다: %s", response.prompt_feedback)
        return None
    return response.parsed


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


def plan_copilot_tool(
    message: str, tool_definitions: tuple[dict, ...]
) -> Optional[CopilotToolPlan]:
    """사용자 요청을 허용 도구 하나로 계획한다. 실제 도구 실행은 하지 않는다."""
    tools_json = json.dumps(tool_definitions, ensure_ascii=False)
    prompt = f"""사용자의 ThermoShift 운영 요청을 처리할 도구 하나를 고르세요.
허용 목록 밖의 이름은 절대 만들지 마세요. 냉난방 제어 요청은 실행 도구가 아니라
propose_control_action, 실험 시작·중단 요청은 각각 propose_experiment_start와
propose_experiment_stop을 선택하세요. '왜 껐어?'처럼 과거 이유를 묻는 질문은
제어 제안이 아니라 get_recent_decisions입니다. 실험 가능 여부는
get_experiment_readiness, 특정 run의 학습 적합성은 get_data_quality를 고르세요.
정보가 부족한 일반 질문은 get_live_snapshot을 선택하세요.

허용 도구:
{tools_json}

사용자 요청:
{message[:1000]}"""
    raw_plan = _call(prompt, _GeminiCopilotToolPlan, effort="low", max_tokens=1500)
    if raw_plan is None:
        return None
    values = raw_plan.model_dump(exclude_none=True)
    tool_name = str(values.pop("tool_name"))
    reason = str(values.pop("selection_reason"))
    # 제안 근거는 모델이 별도로 생성하지 않고 사용자의 원문을 감사 로그용으로 쓴다.
    if tool_name.startswith("propose_"):
        values["reason"] = message[:300]
    return CopilotToolPlan(tool_name=tool_name, arguments=values, reason=reason)
