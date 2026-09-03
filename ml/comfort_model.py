"""PMV/PPD 기반 온열 쾌적도 모델.

온도 한 점을 목표로 삼지 않는다. ISO 7730 계열 Fanger PMV 계산으로 현재
환경을 평가하고, 동일한 모델을 역으로 탐색해 PMV=0에 가까운 온도와 냉방
시 쾌적 허용대역 안에서 가장 높은 온도를 구한다.

주의: PMV는 실제 사용자의 만족도 측정값이 아니다. 평균복사온도, 기류,
활동량, 의복량을 직접 측정하지 않으면 명시된 가정 아래의 comfort proxy다.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional


PMV_COMFORT_LIMIT = 0.5


@dataclass
class ComfortMetrics:
    pmv: float
    ppd: float
    # 화면 가독성을 위한 파생 점수일 뿐 표준 지표나 MPC 목적함수가 아니다.
    comfort_score: float
    category: str
    optimal_temp_c: float
    setback_temp_c: float
    explanation: str


def _pmv_ppd(
    temp_c: float,
    humidity_pct: float,
    air_velocity_m_s: float,
    met: float,
    clo: float,
    mean_radiant_temp_c: float,
) -> tuple[float, float]:
    """ISO 7730 부속서의 Fanger 반복 계산 형태로 PMV/PPD를 반환한다."""
    if not 0.0 <= humidity_pct <= 100.0:
        raise ValueError("humidity_pct must be between 0 and 100")
    if air_velocity_m_s < 0.0 or met <= 0.0 or clo < 0.0:
        raise ValueError("air velocity and clothing must be non-negative; met must be positive")

    pa = humidity_pct * 10.0 * math.exp(16.6536 - 4030.183 / (temp_c + 235.0))
    icl = 0.155 * clo
    m = met * 58.15
    mw = m  # 일반 실내 활동에서 외부 기계적 일은 0으로 가정한다.
    fcl = 1.0 + 1.29 * icl if icl <= 0.078 else 1.05 + 0.645 * icl

    taa = temp_c + 273.0
    tra = mean_radiant_temp_c + 273.0
    tcla = taa + (35.5 - temp_c) / (3.5 * (6.45 * icl + 0.1))
    p1 = icl * fcl
    p2 = p1 * 3.96
    p3 = p1 * 100.0
    p4 = p1 * taa
    p5 = 308.7 - 0.028 * mw + p2 * (tra / 100.0) ** 4
    hcf = 12.1 * math.sqrt(air_velocity_m_s)
    xn = tcla / 100.0
    xf = tcla / 50.0
    hc = hcf

    for _ in range(150):
        xf = (xf + xn) / 2.0
        hcn = 2.38 * abs(100.0 * xf - taa) ** 0.25
        hc = max(hcf, hcn)
        xn = (p5 + p4 * hc - p2 * xn**4) / (100.0 + p3 * hc)
        if abs(xn - xf) <= 0.00015:
            break
    else:
        raise RuntimeError("PMV clothing-surface temperature did not converge")

    tcl = 100.0 * xn - 273.0
    hl1 = 3.05e-3 * (5733.0 - 6.99 * mw - pa)
    hl2 = 0.42 * (mw - 58.15) if mw > 58.15 else 0.0
    hl3 = 1.7e-5 * m * (5867.0 - pa)
    hl4 = 0.0014 * m * (34.0 - temp_c)
    hl5 = 3.96 * fcl * (xn**4 - (tra / 100.0) ** 4)
    hl6 = fcl * hc * (tcl - temp_c)
    thermal_load = mw - hl1 - hl2 - hl3 - hl4 - hl5 - hl6
    pmv = (0.303 * math.exp(-0.036 * m) + 0.028) * thermal_load
    ppd = 100.0 - 95.0 * math.exp(-0.03353 * pmv**4 - 0.2179 * pmv**2)
    return pmv, ppd


def _comfort_temperatures(
    humidity_pct: float,
    air_velocity_m_s: float,
    met: float,
    clo: float,
) -> tuple[float, float]:
    """같은 PMV 모델을 역탐색해 중립점과 냉방 에너지 우선 상한을 구한다."""
    candidates: list[tuple[float, float]] = []
    for index in range(151):
        candidate_temp = 17.0 + 0.1 * index
        candidate_pmv, _ = _pmv_ppd(
            candidate_temp, humidity_pct, air_velocity_m_s, met, clo,
            candidate_temp,  # 복사온도 미계측 가정을 후보에도 동일하게 적용한다.
        )
        candidates.append((candidate_temp, candidate_pmv))

    neutral = min(candidates, key=lambda item: abs(item[1]))[0]
    acceptable = [temp for temp, pmv in candidates if abs(pmv) <= PMV_COMFORT_LIMIT]
    cooling_upper = max(acceptable) if acceptable else neutral
    return round(neutral, 1), round(cooling_upper, 1)


def calculate_pmv_value(
    temp_c: float,
    humidity_pct: float,
    air_velocity_m_s: float = 0.1,
    met: float = 1.1,
    clo: float = 0.5,
    mean_radiant_temp_c: Optional[float] = None,
) -> float:
    """최적화 내부 반복용 PMV 값. 역탐색과 설명 생성을 생략한다."""
    tr = temp_c if mean_radiant_temp_c is None else mean_radiant_temp_c
    pmv, _ = _pmv_ppd(temp_c, humidity_pct, air_velocity_m_s, met, clo, tr)
    return round(max(-3.0, min(3.0, pmv)), 2)


def calculate_pmv(
    temp_c: float,
    humidity_pct: float,
    air_velocity_m_s: float = 0.1,
    met: float = 1.1,
    clo: float = 0.5,
    mean_radiant_temp_c: Optional[float] = None,
) -> ComfortMetrics:
    """PMV/PPD와 동일 모델에서 도출한 냉방 쾌적 온도 범위를 산출한다."""
    tr = temp_c if mean_radiant_temp_c is None else mean_radiant_temp_c
    raw_pmv, raw_ppd = _pmv_ppd(
        temp_c, humidity_pct, air_velocity_m_s, met, clo, tr
    )
    pmv = round(max(-3.0, min(3.0, raw_pmv)), 2)
    ppd = round(max(5.0, min(100.0, raw_ppd)), 1)

    # 이전 UI 호환용 휴리스틱이다. 표준 등급이나 성과 KPI로 사용하지 않는다.
    comfort_score = max(0.0, min(100.0, round(105.0 - ppd * 2.0, 1)))
    if abs(pmv) <= PMV_COMFORT_LIMIT:
        category = "PMV comfort-band"
    elif pmv > PMV_COMFORT_LIMIT:
        category = "PMV warm-discomfort"
    else:
        category = "PMV cool-discomfort"

    optimal_temp_c, setback_temp_c = _comfort_temperatures(
        humidity_pct, air_velocity_m_s, met, clo
    )
    assumptions = f"met={met:.1f}, clo={clo:.1f}, v={air_velocity_m_s:.1f}m/s"
    if abs(pmv) <= PMV_COMFORT_LIMIT:
        explanation = (
            f"PMV {pmv:+.2f}로 모델 쾌적 허용대역입니다. 냉방 시 허용대역의 "
            f"에너지 우선 상한은 {setback_temp_c:.1f}℃입니다 ({assumptions})."
        )
    elif pmv > PMV_COMFORT_LIMIT:
        explanation = (
            f"PMV {pmv:+.2f}로 더운 방향의 모델 불쾌 구간입니다. "
            f"중립점은 {optimal_temp_c:.1f}℃입니다 ({assumptions})."
        )
    else:
        explanation = (
            f"PMV {pmv:+.2f}로 추운 방향의 모델 불쾌 구간입니다. "
            f"냉방 정지가 우선입니다 ({assumptions})."
        )

    return ComfortMetrics(
        pmv=pmv,
        ppd=ppd,
        comfort_score=comfort_score,
        category=category,
        optimal_temp_c=optimal_temp_c,
        setback_temp_c=setback_temp_c,
        explanation=explanation,
    )
