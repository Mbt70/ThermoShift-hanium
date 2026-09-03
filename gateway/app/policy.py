"""제어 정책 — 무엇을 할지 정하는 순수 함수.

controller.py 와 나눈 이유
--------------------------
기존 HVACController.decide() 는 판단·IR 송신·DB 기록·상태 보관을 한 덩어리로
하고 있었다. 그래서 "CO2 가 1500ppm 이고 사람이 있으면 무엇을 하는가" 를
확인하려면 MQTT 와 DB 를 띄워야 했다. 판단만 떼어 내면 입력 하나에 결과
하나인 함수가 되고, 표로 만든 상황들을 그대로 시험할 수 있다.

이 파일은 아무것도 보내지 않고 아무것도 저장하지 않는다. 부작용은 전부
controller.py 가 맡는다.

판단 유형
---------
DB 의 decision_type ENUM(precool·maintain·setback·ventilate·off)을 그대로
쓴다. 기존 게이트웨이는 냉방 ON/OFF 둘뿐이라 스키마가 마련해 둔 구분을
쓰지 않고 있었다.

  precool    예약 시작 전에 미리 식힌다 (열모델이 리드타임을 계산)
  maintain   재실 중이고 더워서 냉방을 돌린다
  setback    재실 중이지만 쾌적 범위 안이다 — 설정을 완화해 전력을 아낀다
  ventilate  CO2 가 기준을 넘었다 — 환기가 먼저다
  off        공실이 확인됐거나 충분히 시원하다

우선순위
--------
아래에서 위로 덮어쓰지 않는다. 위에서 걸리면 거기서 끝난다.

  1. 안전 (센서 끊김 → 현 상태 유지)
  2. 사용자 수동 조작 (잠금 중에는 자동 명령을 내지 않는다)
  3. CO2 위험 (사람의 건강이 전력보다 앞선다)
  4. 예약 예냉 (시각이 정해진 약속이라 뒤로 미룰 수 없다)
  5. 공실 (아무도 없으면 끈다)
  6. 재실 중 온도 판단 (maintain / setback)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # 런타임 의존을 만들지 않는다 — 정책은 ml 패키지 없이도 돈다.
    from ml.thermal_model import ThermalModel


@dataclass
class PolicyConfig:
    """판단 기준값. gateway/config/config.yaml 의 control 절에서 온다."""
    target_temp_c: float = 24.0
    # 목표 온도 ±허용폭이 쾌적 범위다. 이 안에서는 냉방을 돌리지 않는다.
    temp_tolerance_c: float = 1.0
    # 완화 폭. 쾌적 범위 안일 때 목표를 이만큼 올려 잡아 전력을 아낀다.
    setback_delta_c: float = 1.5

    # 순간값 한 번으로 켜고 끄면 센서 잡음에 따라 계속 껐다 켰다 한다.
    # 임계를 이 시간만큼 계속 넘고 있어야 판단을 바꾼다.
    cooling_on_duration_sec: int = 180
    cooling_off_duration_sec: int = 300

    # 액추에이터 보호. 켠 직후 끄거나 끈 직후 켜는 잦은 변동을 막는다.
    minimum_on_time_sec: int = 600
    minimum_off_time_sec: int = 300
    command_rate_limit_sec: int = 120

    co2_warning_ppm: float = 1000.0
    co2_critical_ppm: float = 1500.0

    # 예냉을 이보다 일찍 시작하지 않는다. 리드타임 계산이 빗나가도
    # 밤새 냉방이 도는 일은 없어야 한다.
    precool_max_lead_min: float = 90.0
    internal_heat_drift_c_per_min_per_person: float = 0.0


@dataclass
class ScheduleWindow:
    """다음 예약. 없으면 None 이 들어온다."""
    starts_at: datetime
    ends_at: datetime
    target_temp_c: float
    schedule_id: int | None = None


@dataclass
class PolicyInput:
    now: datetime
    # --- 측정 ---
    temperature_c: float | None
    co2_ppm: float | None
    humidity_pct: float = 50.0
    temp_history: list[tuple[datetime, float]] = field(default_factory=list)
    # --- 추정 ---
    occupancy_state: str = "UNKNOWN"       # EMPTY | TRANSITION | OCCUPIED
    p_occupied: float = 0.0
    headcount_estimate: float = 0.0
    # --- 상태 ---
    current_action: str = "POWER_OFF"
    cooling_on: bool = False
    last_on_at: datetime | None = None
    last_off_at: datetime | None = None
    last_command_at: datetime | None = None
    locked_out: bool = False
    # --- 신선도 ---
    env_fresh: bool = True
    occ_fresh: bool = True
    # --- 맥락 ---
    schedule: ScheduleWindow | None = None
    control_mode: str = "rule"             # monitoring | manual | rule | mpc
    # 열모델. 없으면 예냉을 하지 않는다 (리드타임을 모르는 채로 켤 수 없다).
    thermal: "ThermalModel | None" = None


@dataclass
class PolicyDecision:
    decision_type: str                      # precool|maintain|setback|ventilate|off
    action: str                             # POWER_OFF | COOL_<nn>_AUTO
    target_temp_c: float | None
    execute: bool                           # 실제로 송신해야 하는가
    reasons: list[str]
    # 왜 송신하지 않았는지. 발표에서 "왜 안 켰나" 를 설명할 수 있어야 한다.
    blocked_by: str | None = None


def _cool_action(target_c: float) -> str:
    return f"COOL_{int(round(target_c))}_AUTO"


def _sustained(history: list[tuple[datetime, float]], threshold: float,
               above: bool, duration_sec: int, now: datetime) -> bool:
    """임계를 duration_sec 동안 계속 넘고 있었는가.

    창 안의 표본이 실제로 그 길이를 덮는지도 확인한다. 방금 켜져서 10초치
    자료밖에 없는데 '3분 내내 더웠다' 고 할 수는 없다.
    """
    if not history:
        return False
    cutoff = now - timedelta(seconds=duration_sec)
    window = [(t, v) for t, v in history if t >= cutoff]
    if not window:
        return False
    covered = (now - window[0][0]).total_seconds()
    if covered < duration_sec * 0.8:
        return False
    return all((v >= threshold) if above else (v <= threshold) for _, v in window)


def decide(inp: PolicyInput, cfg: PolicyConfig) -> PolicyDecision:
    """상황 하나를 받아 판단 하나를 돌려준다."""
    reasons: list[str] = []
    target = cfg.target_temp_c
    if inp.schedule and inp.schedule.starts_at <= inp.now <= inp.schedule.ends_at:
        # 예약이 진행 중이면 예약의 목표 온도가 우선한다.
        target = inp.schedule.target_temp_c
        reasons.append(f"예약 진행 중 (목표 {target:.1f}℃)")

    hold = PolicyDecision("maintain" if inp.cooling_on else "off",
                          inp.current_action, target, False, reasons)

    # ---------------- 1. 안전 ----------------
    if not inp.env_fresh:
        # 온도를 모르는 채로 냉방을 켜면 얼마나 식었는지 알 수 없다.
        # 지금 상태를 그대로 두는 것이 가장 덜 위험하다.
        reasons.append("환경 센서 신호 없음 — 현 상태 유지")
        hold.blocked_by = "ENV_STALE"
        return hold

    # ---------------- 2. 수동 잠금 ----------------
    if inp.locked_out:
        reasons.append("사용자 수동 조작 후 잠금 중 — 자동 명령 보류")
        hold.blocked_by = "MANUAL_LOCKOUT"
        return hold

    # ---------------- 3. CO2 ----------------
    # 환기 장치가 없으므로 냉방을 조작하지 않는다. 다만 판단을 ventilate 로
    # 남겨야 사용자에게 창을 열라고 알릴 수 있고, 리포트에서 초과 시간이
    # 집계된다. 냉방 상태는 그대로 둔다 — 창을 여는 동안 냉방을 끄는 판단은
    # 사람이 할 일이다.
    if inp.co2_ppm is not None and inp.co2_ppm >= cfg.co2_critical_ppm:
        reasons.append(f"CO2 {inp.co2_ppm:.0f}ppm — 위험 기준({cfg.co2_critical_ppm:.0f}) 초과, 즉시 환기 필요")
        return PolicyDecision("ventilate", inp.current_action, target, False,
                              reasons, blocked_by="CO2_CRITICAL")

    if inp.co2_ppm is not None and inp.co2_ppm >= cfg.co2_warning_ppm:
        reasons.append(f"CO2 {inp.co2_ppm:.0f}ppm — 환기 권장")

    # ---------------- 4. 예약 예냉 ----------------
    if inp.schedule and inp.now < inp.schedule.starts_at:
        pre = _precool(inp, cfg)
        if pre is not None:
            return pre

    # ---------------- 5. 공실 ----------------
    if inp.occupancy_state == "EMPTY":
        reasons.append(f"공실 확인 (재실 확률 {inp.p_occupied:.2f})")
        return _commit(inp, cfg, "off", "POWER_OFF", target, reasons)

    # ---------------- 6. 전이 ----------------
    if inp.occupancy_state != "OCCUPIED":
        # 들어오는 중인지 나가는 중인지 모르는 구간이다. 여기서 상태를
        # 바꾸면 문 한 번 여닫을 때마다 냉방이 껐다 켜졌다 한다.
        reasons.append(f"재실 판단 보류 ({inp.occupancy_state}) — 현 상태 유지")
        hold.blocked_by = "OCCUPANCY_TRANSITION"
        return hold

    # ---------------- 7. 재실 중 온도 판단 ----------------
    if inp.temperature_c is None:
        reasons.append("온도값 없음 — 현 상태 유지")
        hold.blocked_by = "NO_TEMPERATURE"
        return hold

    # MPC (Model Predictive Control) 최적 제어 모드
    if inp.control_mode == "mpc":
        if inp.thermal is None or not getattr(inp.thermal, "calibrated", False):
            reasons.append("MPC 보류 — 현장 열모델 미교정, 안전 규칙 제어로 대체")
        else:
            mpc_decision = _mpc_decide(inp, cfg)
            if mpc_decision is not None:
                return mpc_decision
            reasons.append("MPC 모듈을 불러오지 못해 안전 규칙 제어로 대체")

    upper = target + cfg.temp_tolerance_c
    lower = target - cfg.temp_tolerance_c
    reasons.append(f"재실 중 · 실내 {inp.temperature_c:.1f}℃ "
                   f"(쾌적 {lower:.1f}~{upper:.1f}℃)")

    if _sustained(inp.temp_history, upper, True,
                  cfg.cooling_on_duration_sec, inp.now):
        reasons.append(f"{upper:.1f}℃ 초과가 {cfg.cooling_on_duration_sec//60}분 지속")
        return _commit(inp, cfg, "maintain", _cool_action(target), target, reasons)

    if _sustained(inp.temp_history, lower, False,
                  cfg.cooling_off_duration_sec, inp.now):
        reasons.append(f"{lower:.1f}℃ 미만이 {cfg.cooling_off_duration_sec//60}분 지속 — 과냉")
        return _commit(inp, cfg, "off", "POWER_OFF", target, reasons)

    # 여기까지 왔다는 것은 "지속 조건을 아직 못 채웠다" 는 뜻이다. 온도가
    # 범위 밖이어도 그것이 충분히 오래 유지되지 않았으면 판단을 바꾸지 않는다.
    # 근거 문구가 이 둘을 구분해야 한다 — 예전에는 범위 밖인데도 "쾌적 범위
    # 안" 이라고 적어서, 27℃ 인 방의 제어 로그에 "쾌적 범위 안" 이 남았다.
    if inp.temperature_c > upper:
        reasons.append(
            f"{upper:.1f}℃ 초과이지만 {cfg.cooling_on_duration_sec // 60}분 지속 "
            "조건 미충족 — 관측 계속")
        hold.blocked_by = "AWAITING_SUSTAINED_HIGH"
        return hold

    if inp.temperature_c < lower:
        reasons.append(
            f"{lower:.1f}℃ 미만이지만 {cfg.cooling_off_duration_sec // 60}분 지속 "
            "조건 미충족 — 관측 계속")
        hold.blocked_by = "AWAITING_SUSTAINED_LOW"
        return hold

    # 진짜로 쾌적 범위 안이다.
    if inp.cooling_on:
        relaxed = target + cfg.setback_delta_c
        reasons.append(f"쾌적 범위 안 — 설정을 {relaxed:.1f}℃ 로 완화(setback)")
        return _commit(inp, cfg, "setback", _cool_action(relaxed), relaxed, reasons)

    reasons.append("쾌적 범위 안 · 냉방 정지 유지")
    return PolicyDecision("off", "POWER_OFF", target, False, reasons)


def _precool(inp: PolicyInput, cfg: PolicyConfig) -> PolicyDecision | None:
    """예약 시작에 맞춰 미리 식혀야 하는지 본다. 아니면 None.

    "몇 분 전에 켜야 하는가" 를 사람이 적어 넣지 않고 열모델이 현재 온도에서
    계산한다. 더운 날은 일찍, 이미 시원하면 아예 켜지 않는다.
    """
    sched = inp.schedule
    if (inp.temperature_c is None or inp.thermal is None
            or not getattr(inp.thermal, "calibrated", False)):
        return None

    lead = inp.thermal.lead_time_minutes(inp.temperature_c, sched.target_temp_c)
    minutes_left = (sched.starts_at - inp.now).total_seconds() / 60.0

    if lead is None:
        # 계속 켜도 목표에 못 닿는다. 일찍 켠다고 해결되지 않으므로
        # 예약 시각에 정상 판단으로 넘긴다.
        if minutes_left <= 0:
            return None
        return None

    if lead <= 0:
        return None  # 이미 충분히 시원하다

    lead = min(lead, cfg.precool_max_lead_min)
    if minutes_left > lead:
        return None  # 아직 이르다

    reasons = [
        f"{minutes_left:.0f}분 뒤 예약 시작 (목표 {sched.target_temp_c:.1f}℃)",
        f"현재 {inp.temperature_c:.1f}℃ → 도달까지 {lead:.0f}분 필요",
    ]
    return _commit(inp, cfg, "precool", _cool_action(sched.target_temp_c),
                   sched.target_temp_c, reasons)


def _commit(inp: PolicyInput, cfg: PolicyConfig, decision_type: str,
            action: str, target: float | None,
            reasons: list[str]) -> PolicyDecision:
    """판단이 섰다. 실제로 보내도 되는지 기기 보호 조건을 확인한다.

    보내지 못하더라도 판단 자체는 그대로 돌려준다. 무엇을 하려 했는지가
    기록에 남아야 나중에 "왜 안 켜졌나" 를 설명할 수 있다.
    """
    if action == inp.current_action:
        return PolicyDecision(decision_type, action, target, False, reasons)

    turning_on = action != "POWER_OFF"

    if turning_on and inp.last_off_at is not None:
        idle = (inp.now - inp.last_off_at).total_seconds()
        if idle < cfg.minimum_off_time_sec:
            reasons.append(
                f"정지 후 {idle:.0f}초 — 최소 정지시간 {cfg.minimum_off_time_sec}초 미달")
            return PolicyDecision(decision_type, inp.current_action, target,
                                  False, reasons, blocked_by="MIN_OFF_TIME")

    if not turning_on and inp.last_on_at is not None:
        run = (inp.now - inp.last_on_at).total_seconds()
        if run < cfg.minimum_on_time_sec:
            reasons.append(
                f"가동 후 {run:.0f}초 — 최소 가동시간 {cfg.minimum_on_time_sec}초 미달")
            return PolicyDecision(decision_type, inp.current_action, target,
                                  False, reasons, blocked_by="MIN_ON_TIME")

    if inp.last_command_at is not None:
        since = (inp.now - inp.last_command_at).total_seconds()
        if since < cfg.command_rate_limit_sec:
            reasons.append(f"직전 명령 후 {since:.0f}초 — 명령 간격 제한")
            return PolicyDecision(decision_type, inp.current_action, target,
                                  False, reasons, blocked_by="RATE_LIMIT")

    if inp.control_mode == "monitoring":
        # 관측 전용. 판단은 다 하되 송신만 하지 않는다. baseline 구간을
        # 만들 때 이 모드로 돌린다.
        reasons.append("관측 모드 — 판단만 기록하고 송신하지 않음")
        return PolicyDecision(decision_type, action, target, False, reasons,
                              blocked_by="MONITORING_MODE")

    return PolicyDecision(decision_type, action, target, True, reasons)


def _mpc_decide(inp: PolicyInput, cfg: PolicyConfig) -> PolicyDecision | None:
    """전력 소비량과 PMV 쾌적도를 동시 최적화하는 다목적 경제적 MPC 의사결정."""
    try:
        from ml.mpc_controller import ModelPredictiveController
    except ImportError:
        return None

    sched_minutes = None
    if inp.schedule and inp.now < inp.schedule.starts_at:
        sched_minutes = (inp.schedule.starts_at - inp.now).total_seconds() / 60.0

    # 현재는 실제 전력회사 요금표 연동 전인 목업 시나리오다. UTC 시각을 그대로
    # 14시로 해석하지 않고 실증 지역(KST)의 14:00~17:00만 가중한다.
    local_hour = inp.now.astimezone(ZoneInfo("Asia/Seoul")).hour
    peak_hour = 14 <= local_hour < 17
    mpc = ModelPredictiveController()
    sol = mpc.solve(
        current_temp_c=inp.temperature_c,
        humidity_pct=inp.humidity_pct,
        p_occupied=inp.p_occupied,
        thermal_model=inp.thermal,
        target_temp_setting=cfg.target_temp_c,
        schedule_in_minutes=sched_minutes,
        current_cooling_on=inp.cooling_on,
        headcount_estimate=inp.headcount_estimate,
        heat_drift_c_per_min_per_person=cfg.internal_heat_drift_c_per_min_per_person,
        peak_hour=peak_hour,
    )
    return _commit(inp, cfg, sol.decision_type, sol.optimal_action, sol.target_temp_c, sol.reasons)
