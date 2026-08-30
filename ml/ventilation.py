"""환기량 식별 — 문 개폐를 계단 입력으로 쓰는 시스템 식별.

무엇을 푸는가
-------------
공간의 CO2 는 질량보존을 따른다.

    dC/dt = ( N·G_c − Q·(C − C_out) ) / V

    C 실내 CO2(ppm)   N 재실 인원   G_c 1인당 발생량
    Q 환기량(㎥/h)     V 체적(㎥)    C_out 외기 CO2(≈420ppm)

여기서 Q 는 문·창문 상태에 따라 몇 배씩 달라진다. 이 값을 모르면
  - 재실 추정이 CO2 상승을 사람 탓인지 환기 탓인지 구분하지 못하고
  - 환기 권고(ventilate 판단)를 언제 내려야 하는지 정할 수 없다.

핵심: 재실이 '0' 일 필요는 없다
--------------------------------
위 식을 정리하면

    dC/dt = −k·C + b,      k = Q/V,   b = k·C_out + N·G_c/V

N 이 구간 안에서 **일정하기만 하면** b 는 상수가 되고, k 는 그대로
식별된다. 즉 빈 방을 만들 필요 없이 "인원이 변하지 않는 구간"이면 된다.
현장에서 방을 비우는 것보다 훨씬 지키기 쉬운 조건이다.

k 를 얻으면 시간당 환기횟수(ACH)는 k·60 이다.

왜 미분이 아니라 적분인가
-------------------------
dC/dt 를 차분으로 만들면 센서 잡음이 그대로 증폭된다(미분은 고주파를
키운다). 대신 위 식을 t0..t 로 적분하면

    C(t) − C(t0) = −k·∫C dt + b·(t − t0)

가 되고, 적분은 잡음을 눌러 준다. 좌변을 (∫C dt, t−t0) 두 변수로
회귀하면 k 와 b 가 한 번에 나온다. 짧고 지저분한 구간에서 훨씬 안정적이다.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timedelta

# 실외 CO2. 추정된 b 로부터 재실 기여분을 떼어낼 때 기준으로 쓴다.
OUTDOOR_CO2_PPM = 420.0

# --- 식별에 필요한 최소 근거 -----------------------------------------
# 구간이 시정수(1/k)에 비해 너무 짧으면 지수곡선이 직선과 구분되지 않아
# k 가 사실상 임의값이 된다. 닫힌 방의 k 는 대개 0.01~0.03/분(τ 30~100분),
# 문을 연 방은 0.05~0.2/분(τ 5~20분) 범위다.
MIN_DURATION_SEC = {"open": 600, "closed": 1800}
MIN_SAMPLES = 30
# 구간 안에서 CO2 가 이만큼은 움직여야 감쇠를 볼 수 있다.
MIN_CO2_RANGE_PPM = 40.0
# 재실이 구간 내내 일정해야 b 가 상수가 된다.
#
# 처음에는 "PIR 상태 변화 횟수"로 판정했는데 틀린 지표였다. PIR 은 1Hz 로
# 읽히고 사람이 가만히 앉아 있어도 계속 깜빡인다. 실제로 38분짜리 구간이
# 변화 140회로 거절됐다 — 사람이 140번 드나든 게 아니라 한 명이 앉아 있던
# 것이다.
#
# 필요한 것은 "움직임의 양이 구간 내내 비슷한가" 이다. 구간을 반으로 갈라
# PIR 점유율(활동 비율)을 비교해, 차이가 크면 사람이 드나든 것으로 본다.
MAX_PIR_DUTY_SHIFT = 0.25
# 물리적으로 가능한 범위. 밖으로 나가면 센서 교란이나 잘못된 구간이다.
K_BOUNDS = (0.001, 0.5)      # 1/분  → ACH 0.06 ~ 30

# 구간 중 실내 온도가 이보다 크게 흔들리면 센서가 건드려졌거나 문/창문
# 외의 무언가가 일어난 것으로 본다.
#
# 근거: 2026-08-25 기록에서 조용한 90분 구간의 온도 폭은 0.16℃ 였다. 방의
# 열용량 때문에 정상 상태에서는 이 정도가 한계다. 그런데 07:19~07:30 의
# 11분 구간은 2.28℃ 가 흔들렸고, 같은 시각 습도도 반대로 움직였다 —
# 노드가 옮겨졌거나 사람이 가까이서 만진 흔적이다. 이 구간은 CO2 만 보면
# 그럴듯한 값(ACH 11.5, R² 0.78)이 나오지만 믿을 수 없다.
MAX_TEMP_SWING_C = 1.0


MEASUREMENT_PROTOCOL = """\
환기량 식별을 위한 측정 절차 (약 1시간, 1회)

  준비: 사람 수를 정해 놓고 **구간 내내 바꾸지 않는다**. 방을 비울 필요는
        없다. 2명이 앉아 있어도 되고, 그 2명이 계속 있기만 하면 된다.

  1. 문·창문을 닫고 30분 유지          -> k_closed
     (CO2 가 40ppm 이상 움직여야 한다. 안 움직이면 사람을 늘리거나
      시작 전에 환기해 CO2 를 낮춰 두고 시작한다.)

  2. 문을 열고 15분 유지               -> k_open
  3. 다시 닫고 15분                    -> 재현성 확인

  하지 말아야 할 것
    - 센서 근처에서 말하거나 숨을 뱉지 않는다. 지난 기록의 4,248ppm 스파이크는
      환기가 아니라 센서에 직접 숨이 닿은 흔적이었다.
    - 구간 도중 사람이 드나들지 않는다.
    - 센서 노드를 옮기지 않는다.

  끝나면:  python -m ml.analyze_ventilation --source postgres
"""


@dataclass
class Segment:
    state: str                 # "open" | "closed"
    started_at: datetime
    ended_at: datetime
    samples: list[tuple[datetime, float]]     # (시각, CO2)
    # 구간 전반부·후반부의 PIR 점유율. 둘이 비슷하면 인원이 유지된 것으로 본다.
    pir_duty_first: float | None = None
    pir_duty_second: float | None = None
    # 구간 중 실내 온도 변동폭(℃). 센서 교란을 잡는다.
    temp_swing_c: float | None = None

    @property
    def pir_duty_shift(self) -> float | None:
        if self.pir_duty_first is None or self.pir_duty_second is None:
            return None
        return abs(self.pir_duty_first - self.pir_duty_second)

    @property
    def duration_sec(self) -> float:
        return (self.ended_at - self.started_at).total_seconds()

    @property
    def co2_range(self) -> float:
        if not self.samples:
            return 0.0
        v = [c for _, c in self.samples]
        return max(v) - min(v)


@dataclass
class Estimate:
    """한 구간의 식별 결과. k 가 None 이면 근거가 모자란 것이다."""
    segment: Segment
    k_per_min: float | None
    b: float | None
    r2: float | None
    reasons: list[str]

    @property
    def ach(self) -> float | None:
        """시간당 환기횟수."""
        return None if self.k_per_min is None else self.k_per_min * 60.0

    @property
    def tau_min(self) -> float | None:
        return None if not self.k_per_min else 1.0 / self.k_per_min

    def occupant_term(self) -> float | None:
        """b 에서 외기 기여를 뺀 나머지 = N·G_c/V (ppm/분).

        인원이 몇 명인지 알면 1인당 발생량을, 발생량을 알면 인원을 얻는다.
        이중 물리 결합(에너지+질량)으로 인원수를 추정할 때 쓰는 값이다.
        """
        if self.k_per_min is None or self.b is None:
            return None
        return self.b - self.k_per_min * OUTDOOR_CO2_PPM


def assess(seg: Segment) -> list[str]:
    """이 구간으로 k 를 잴 수 있는지. 못 재는 이유들을 돌려준다."""
    out = []
    need = MIN_DURATION_SEC.get(seg.state, 600)
    if seg.duration_sec < need:
        out.append(f"길이 {seg.duration_sec:.0f}초 (최소 {need}초). "
                   "시정수에 비해 짧아 지수감쇠가 직선과 구분되지 않습니다.")
    if len(seg.samples) < MIN_SAMPLES:
        out.append(f"표본 {len(seg.samples)}개 (최소 {MIN_SAMPLES}).")
    if seg.co2_range < MIN_CO2_RANGE_PPM:
        out.append(f"CO2 변화폭 {seg.co2_range:.0f}ppm (최소 {MIN_CO2_RANGE_PPM:.0f}). "
                   "농도가 거의 안 움직여 감쇠를 볼 수 없습니다.")
    if seg.temp_swing_c is not None and seg.temp_swing_c > MAX_TEMP_SWING_C:
        out.append(f"구간 중 실내 온도가 {seg.temp_swing_c:.2f}℃ 흔들렸습니다 "
                   f"(최대 {MAX_TEMP_SWING_C:.1f}℃). 방의 열용량으로는 이만큼 "
                   "빨리 변할 수 없으므로 센서가 건드려진 구간으로 봅니다.")

    shift = seg.pir_duty_shift
    if shift is not None and shift > MAX_PIR_DUTY_SHIFT:
        out.append(f"PIR 점유율이 전반 {seg.pir_duty_first:.0%} → 후반 "
                   f"{seg.pir_duty_second:.0%} 로 {shift:.0%} 바뀌었습니다 "
                   f"(최대 {MAX_PIR_DUTY_SHIFT:.0%}). 인원이 달라진 것으로 보여 "
                   "발생항을 상수로 둘 수 없습니다.")
    return out


def identify(seg: Segment) -> Estimate:
    """적분법 최소제곱으로 k, b 를 추정한다."""
    reasons = assess(seg)
    if reasons:
        return Estimate(seg, None, None, None, reasons)

    pts = sorted(seg.samples)
    t0 = pts[0][0]
    # 사다리꼴 적분으로 ∫C dt 를 누적한다.
    xs, ys = [], []
    integral = 0.0
    for (ta, ca), (tb, cb) in zip(pts, pts[1:]):
        dt = (tb - ta).total_seconds() / 60.0
        if dt <= 0:
            continue
        integral += 0.5 * (ca + cb) * dt
        xs.append((integral, (tb - t0).total_seconds() / 60.0))
        ys.append(cb - pts[0][1])

    if len(xs) < MIN_SAMPLES:
        reasons.append(f"적분 표본이 {len(xs)}개뿐입니다.")
        return Estimate(seg, None, None, None, reasons)

    # y = β1·∫C + β2·t   (β1 = −k, β2 = b) — 절편 없는 2변수 회귀
    s11 = sum(a * a for a, _ in xs)
    s22 = sum(b * b for _, b in xs)
    s12 = sum(a * b for a, b in xs)
    t1 = sum(a * y for (a, _), y in zip(xs, ys))
    t2 = sum(b * y for (_, b), y in zip(xs, ys))
    det = s11 * s22 - s12 * s12
    if abs(det) < 1e-12:
        reasons.append("설계행렬이 특이합니다 — 적분항과 시간항이 구분되지 않습니다.")
        return Estimate(seg, None, None, None, reasons)

    beta1 = (t1 * s22 - t2 * s12) / det
    beta2 = (t2 * s11 - t1 * s12) / det
    k, b = -beta1, beta2

    mean_y = sum(ys) / len(ys)
    ss_tot = sum((y - mean_y) ** 2 for y in ys)
    ss_res = sum((y - (beta1 * a + beta2 * t)) ** 2
                 for (a, t), y in zip(xs, ys))
    r2 = 1.0 - ss_res / ss_tot if ss_tot > 0 else 0.0

    if not (K_BOUNDS[0] <= k <= K_BOUNDS[1]):
        reasons.append(
            f"k={k:.4f}/분 (ACH {k*60:.1f}) 가 물리적 범위를 벗어납니다 "
            f"(허용 ACH {K_BOUNDS[0]*60:.2f}~{K_BOUNDS[1]*60:.0f}). "
            "센서 교란이나 구간 설정 오류로 봅니다.")
    if r2 < 0.5:
        reasons.append(f"설명력 R²={r2:.3f} 이 낮습니다.")
    if reasons:
        return Estimate(seg, None, None, r2, reasons)

    return Estimate(seg, k, b, r2, [])


def compare(estimates: list[Estimate]) -> tuple[dict, list[str]]:
    """열림/닫힘 k 를 비교한다. 결론을 못 내면 이유를 함께 돌려준다."""
    ok = [e for e in estimates if e.k_per_min is not None]
    by = {"open": [e for e in ok if e.segment.state == "open"],
          "closed": [e for e in ok if e.segment.state == "closed"]}
    summary = {s: {"n": len(v),
                   "ach": [round(e.ach, 2) for e in v],
                   "mean_ach": (sum(e.ach for e in v) / len(v)) if v else None}
               for s, v in by.items()}

    problems = []
    for s in ("open", "closed"):
        if not by[s]:
            problems.append(f"{'열림' if s=='open' else '닫힘'} 구간에서 "
                            "식별에 성공한 것이 없습니다.")
    if by["open"] and by["closed"]:
        mo, mc = summary["open"]["mean_ach"], summary["closed"]["mean_ach"]
        if mo <= mc:
            problems.append(
                f"문을 연 쪽 환기횟수(ACH {mo:.2f})가 닫은 쪽(ACH {mc:.2f})보다 "
                "크지 않습니다. 물리적으로 뒤집힌 결과이므로 구간 설정이나 "
                "센서를 다시 봐야 합니다.")
        # 겹침 확인 — 평균만 보면 분산을 놓친다.
        lo_o = min(e.ach for e in by["open"])
        hi_c = max(e.ach for e in by["closed"])
        if lo_o <= hi_c:
            problems.append(
                f"두 조건의 값 범위가 겹칩니다 (열림 최소 {lo_o:.2f} ≤ "
                f"닫힘 최대 {hi_c:.2f}). 구간 수를 늘려야 분리됩니다.")
    return summary, problems
