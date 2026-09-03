"""ASHRAE 55 / ISO 7730 표준 기반 열쾌적도(PMV/PPD) 모델 및 에너지 최적화.

기존의 고정 온도(예: 24℃) 방식의 한계:
- 습도가 80%인 날의 24℃는 덥고 끈적이며, 습도가 35%인 날의 24℃는 서늘하다.
- 온도가 25℃여도 습도와 통풍이 적절하면 사람은 매우 쾌적함을 느낀다.
- 따라서 Fanger PMV(Predicted Mean Vote) 공식을 적용해 실시간 온·습도에 따른
  '체감 쾌적 밴드(-0.5 <= PMV <= +0.5)'를 도출하고, 그 안에서 전력을 가장 아끼는
  최적 설정온도(Setback)를 수학적으로 계산한다.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional


@dataclass
class ComfortMetrics:
    pmv: float                  # Predicted Mean Vote (-3: 한랭 ~ 0: 쾌적 ~ +3: 더움)
    ppd: float                  # Predicted Percentage of Dissatisfied (%)
    comfort_score: float        # 0 ~ 100 점 (80점 이상이면 양호/쾌적)
    category: str               # "Category A" (|PMV|<=0.2), "Category B" (|PMV|<=0.5), "Category C" (|PMV|<=0.7), "Discomfort"
    optimal_temp_c: float       # PMV=0 을 달성하는 중립 온도 (℃)
    setback_temp_c: float       # 쾌적 범위(|PMV|<=0.5) 안에서 에너지를 아끼는 완화 온도 (℃)
    explanation: str            # 관리자/심사위원을 위한 직관적인 한국어 설명


def calculate_saturated_vapor_pressure(temp_c: float) -> float:
    """포화수증기압 (Pa) - Antoine / ASHRAE 근사식."""
    return 100.0 * math.exp(18.956 - 4030.18 / (temp_c + 235.0))


def calculate_pmv(
    temp_c: float,
    humidity_pct: float,
    air_velocity_m_s: float = 0.1,
    met: float = 1.1,           # 일반 사무/학습: 1.1 met (약 64 W/m²)
    clo: float = 0.5,           # 여름철 가벼운 실내복: 0.5 clo
    mean_radiant_temp_c: Optional[float] = None,
) -> ComfortMetrics:
    """ISO 7730 / ASHRAE 55 PMV 및 PPD를 산출한다.

    Args:
        temp_c: 실내 건구온도 (℃)
        humidity_pct: 상대습도 (0 ~ 100 %)
        air_velocity_m_s: 실내 기류속도 (기본 0.1 m/s)
        met: 대사율 (기본 1.1 met)
        clo: 의복 단열력 (기본 0.5 clo)
        mean_radiant_temp_c: 평균 복사온도 (None이면 건구온도와 같다고 가정)
    """
    if mean_radiant_temp_c is None:
        mean_radiant_temp_c = temp_c

    # 물리 상수 및 단위 변환
    m = met * 58.15             # W/m² (대사열)
    w = 0.0                     # 외부 기계적 일 (일반 실내 사무에서는 0)
    mw = m - w

    icl = 0.155 * clo           # m²·K/W (의복 열저항)
    fcl = 1.0 + 0.2 * clo if clo <= 0.5 else 1.05 + 0.1 * clo  # 의복 표면적 계수

    # 수증기 분압 (Pa)
    p_sat = calculate_saturated_vapor_pressure(temp_c)
    pa = (humidity_pct / 100.0) * p_sat

    # 열전달 계수 수렴 계산 (반복법)
    taa = temp_c + 273.15
    tra = mean_radiant_temp_c + 273.15
    tcl = taa + (35.5 - temp_c) / (3.5 * (6.45 * icl + 0.1))  # 초기 추정값

    hcf = 12.1 * math.sqrt(air_velocity_m_s)
    for _ in range(50):
        # 자연대류 vs 강제대류
        hcn = 2.38 * math.pow(abs(tcl - taa), 0.25)
        hc = max(hcf, hcn)

        # 의복 표면온도 수렴식
        rad = 3.96e-8 * fcl * (math.pow(tcl, 4) - math.pow(tra, 4))
        conv = fcl * hc * (tcl - taa)
        tcl_new = 35.7 - 0.028 * mw - icl * (rad + conv) + 273.15
        if abs(tcl_new - tcl) < 0.001:
            tcl = tcl_new
            break
        tcl = 0.8 * tcl + 0.2 * tcl_new

    # 인체 열부하 L (W/m²)
    # 1) 피부를 통한 수분 증발 (확산)
    hl1 = 3.05e-3 * (5733.0 - 6.99 * mw - pa)
    # 2) 땀 분비에 의한 열손실
    hl2 = 0.42 * (mw - 58.15) if mw > 58.15 else 0.0
    # 3) 호흡 잠열 손실
    hl3 = 1.7e-5 * m * (5867.0 - pa)
    # 4) 호흡 현열 손실
    hl4 = 0.0014 * m * (34.0 - temp_c)
    # 5) 복사 열손실
    hl5 = 3.96e-8 * fcl * (math.pow(tcl, 4) - math.pow(tra, 4))
    # 6) 대류 열손실
    hl6 = fcl * hc * (tcl - taa)

    thermal_load = mw - hl1 - hl2 - hl3 - hl4 - hl5 - hl6

    # PMV 계산
    pmv = (0.303 * math.exp(-0.036 * m) + 0.028) * thermal_load
    pmv = max(-3.0, min(3.0, round(pmv, 2)))

    # PPD 계산 (예측 불만족률, %)
    ppd = 100.0 - 95.0 * math.exp(-0.03353 * math.pow(pmv, 4) - 0.2179 * math.pow(pmv, 2))
    ppd = max(5.0, min(100.0, round(ppd, 1)))

    # 쾌적도 점수 (100점 만점)
    # PPD 5%(최적) -> 100점, PPD 10%(Class B 상한) -> 85점, PPD 20% -> 60점
    comfort_score = max(0.0, min(100.0, round(105.0 - ppd * 2.0, 1)))

    # ISO 7730 등급 분류
    abs_pmv = abs(pmv)
    if abs_pmv <= 0.2:
        category = "Category A (최상)"
    elif abs_pmv <= 0.5:
        category = "Category B (쾌적)"
    elif abs_pmv <= 0.7:
        category = "Category C (보통)"
    else:
        category = "Discomfort (불쾌)"

    # 습도에 따른 최적 중립 온도(PMV=0) 및 완화 온도(PMV=0.5) 역산 근사
    neutral_temp = 24.5 - 0.025 * (humidity_pct - 50.0)
    setback_temp = neutral_temp + 1.2  # PMV ≈ +0.45 부근 (쾌적 범위를 지키면서 최대 절전)

    optimal_temp_c = round(neutral_temp, 1)
    setback_temp_c = round(setback_temp, 1)

    # 설명 문구 생성
    if abs_pmv <= 0.5:
        if humidity_pct > 65:
            exp = f"PMV {pmv:+.2f}로 쾌적 범위이나 습도({humidity_pct:.0f}%)가 높아 체감 온도가 높습니다. 완화 상한 {setback_temp_c:.1f}℃ 권장."
        elif humidity_pct < 40:
            exp = f"PMV {pmv:+.2f} (쾌적). 건조한 편이므로 목표온도를 {setback_temp_c:.1f}℃로 완화(Setback)해 전력을 절감할 수 있습니다."
        else:
            exp = f"PMV {pmv:+.2f} (쾌적, 만족도 {100-ppd:.0f}%). 전력 최소화 완화 목표온도는 {setback_temp_c:.1f}℃입니다."
    elif pmv > 0.5:
        exp = f"PMV {pmv:+.2f}로 온열감 높음 (불만족률 {ppd:.0f}%). 냉방을 가동해 중립온도 {optimal_temp_c:.1f}℃로 냉각이 필요합니다."
    else:
        exp = f"PMV {pmv:+.2f}로 과냉각 상태 (불만족률 {ppd:.0f}%). 냉방을 즉시 정지하거나 온도를 올려 전력 낭비를 방지하세요."

    return ComfortMetrics(
        pmv=pmv,
        ppd=ppd,
        comfort_score=comfort_score,
        category=category,
        optimal_temp_c=optimal_temp_c,
        setback_temp_c=setback_temp_c,
        explanation=exp,
    )
