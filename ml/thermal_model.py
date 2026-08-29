"""공간 열모델 — 예냉(pre-cooling) 리드타임 산출용.

무엇을 푸는가
-------------
"14시 수업 시작에 맞춰 24℃ 를 만들려면 몇 분 전에 냉방을 켜야 하는가."
이 질문에 답하려면 방이 얼마나 빨리 식는지를 알아야 한다. 스케줄에
precooling_min 을 사람이 손으로 적어 넣는 대신 모델이 계산하게 한다.

모델
----
단일 존 1차 RC 모델을 회귀가 가능한 형태로 정리해 쓴다.

    dT/dt = -a·T + d + b·u

    T  실내 온도(℃)          u  냉방 가동 여부 (0/1)
    a  1/시정수 (1/분)        b  냉방 냉각률 (℃/분, 음수)
    d  외기·내부발열이 합쳐진 표류항 (℃/분)

외기 온도를 따로 재지 않으므로 (a·T_out + 내부발열) 을 d 하나로 묶었다.
d 를 상수로 두는 것은 몇 시간 단위에서만 맞는 근사다. 하루를 넘겨 쓰려면
d 를 시간대별로 나눠야 한다.

해가 있으므로 리드타임은 닫힌 형태로 나온다. u=1 로 고정하면

    T(t) = T∞ + (T0 - T∞)·exp(-a·t),   T∞ = (d + b)/a

    t = -(1/a)·ln( (T_target - T∞) / (T0 - T∞) )

왜 지금 데이터로는 못 맞추는가
------------------------------
회귀가 a 와 b 를 분리하려면 (1) 온도가 실제로 움직여야 하고 (2) 냉방이
켜진 구간과 꺼진 구간이 둘 다 있어야 한다. 2026-08-25 기록은 05:30~07:00
90분 동안 24.35℃ ± 0.16℃ 로 사실상 등온이었고, 냉방 송신은 딱 1회였다.
여기서 나오는 a, b 는 잡음을 맞춘 숫자일 뿐이다.

그래서 `identify()` 는 근거가 모자라면 값을 만들어 내지 않고 이유를 담아
거절한다. 필요한 자료는 `STEP_TEST_GUIDE` 의 30분짜리 실험 한 번이면 된다.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path

# ---------------------------------------------------------------------
# 교정 전 기본값.
#
# 실측이 아니라 소형 강의실(약 60㎥) + 벽걸이형 냉방기를 가정한 값이다.
# 시연이 멈추지 않도록 두는 것이지 이 값이 맞다는 뜻이 아니다. calibrated
# 플래그로 구분되며, 교정 전에는 UI·리포트에 '가정값' 으로 표시해야 한다.
#
#   a = 0.006 /분  → 시정수 약 167분 (패시브로 외기에 수렴하는 속도)
#   b = -0.05 ℃/분 → 냉방 가동 시 초기 냉각률 약 3℃/시간
#   d = 0.15 ℃/분  → a·T_out + 내부발열. T_out=25℃ 부근에서 균형을 이루는 값
# ---------------------------------------------------------------------
DEFAULT_A = 0.006
DEFAULT_B = -0.05
DEFAULT_D = 0.15

# 식별에 필요한 최소 근거
MIN_SAMPLES = 60            # 표본 수
MIN_TEMP_RANGE_C = 0.8      # 온도가 이만큼은 움직여야 a 를 잴 수 있다
MIN_COOLING_SAMPLES = 20    # u=1 구간이 이만큼은 있어야 b 가 분리된다
MIN_IDLE_SAMPLES = 20       # u=0 구간도 있어야 a 와 b 가 섞이지 않는다
MIN_R2 = 0.30               # 이보다 낮으면 모델이 데이터를 설명하지 못한다


STEP_TEST_GUIDE = """\
열모델 교정 실험 (30~40분, 1회)

  1. 방을 비운다. 사람이 있으면 내부발열이 섞여 a 와 d 가 흐려진다.
  2. 냉방을 끈 채 10분 기다린다.            → u=0 구간
  3. 냉방을 최저 설정으로 20분 켠다.        → u=1 구간, 온도가 내려간다
  4. 다시 끄고 10분 기다린다.               → u=0 구간, 되오르는 속도
  5. 그동안 게이트웨이가 계속 기록하게 둔다.

  이때 온도가 최소 0.8℃ 는 움직여야 한다. 움직이지 않으면 냉방 출력이
  모자라거나 문이 열려 있는 것이므로 조건을 바꿔 다시 한다.

  끝나면:  python -m ml.train_thermal --source postgres --since <실험 시작 시각>
"""


@dataclass
class ThermalModel:
    a: float = DEFAULT_A          # 1/분
    b: float = DEFAULT_B          # ℃/분 (냉방, 음수)
    d: float = DEFAULT_D          # ℃/분
    calibrated: bool = False
    r2: float | None = None
    metadata: dict | None = None

    # ---------------- 물리량 ----------------
    @property
    def time_constant_min(self) -> float:
        return 1.0 / self.a if self.a > 0 else float("inf")

    def steady_state(self, cooling: bool) -> float:
        """냉방을 계속 켜(끄)면 결국 도달하는 온도."""
        return (self.d + (self.b if cooling else 0.0)) / self.a

    # ---------------- 예측 ----------------
    def predict(self, t0_c: float, minutes: float, cooling: bool) -> float:
        """minutes 분 뒤 온도."""
        inf = self.steady_state(cooling)
        return inf + (t0_c - inf) * math.exp(-self.a * minutes)

    def trajectory(self, t0_c: float, minutes: float, cooling: bool,
                   step: float = 1.0) -> list[tuple[float, float]]:
        """(분, 온도) 궤적. 대시보드에서 예측선을 그릴 때 쓴다."""
        out, t = [], 0.0
        while t <= minutes:
            out.append((t, self.predict(t0_c, t, cooling)))
            t += step
        return out

    # ---------------- 예냉 리드타임 ----------------
    def lead_time_minutes(self, t0_c: float, target_c: float,
                          cap_minutes: float = 180.0) -> float | None:
        """target_c 에 닿기까지 냉방을 몇 분 돌려야 하는지.

        이미 목표 이하면 0. 냉방을 계속 켜도 목표에 못 닿으면 None —
        이 경우 예냉을 아무리 일찍 시작해도 소용없으므로, 호출부는
        '용량 부족' 으로 처리해야지 리드타임을 늘리면 안 된다.
        """
        if t0_c <= target_c:
            return 0.0
        inf = self.steady_state(cooling=True)
        if inf >= target_c:
            return None
        ratio = (target_c - inf) / (t0_c - inf)
        if ratio <= 0:
            return None
        minutes = -math.log(ratio) / self.a
        return min(minutes, cap_minutes)

    # ---------------- 직렬화 ----------------
    def save(self, path: str | Path) -> None:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(asdict(self), indent=2, ensure_ascii=False))

    @classmethod
    def load(cls, path: str | Path) -> "ThermalModel":
        return cls(**json.loads(Path(path).read_text()))


# =====================================================================
@dataclass
class Identification:
    """식별 시도의 결과. 성공하지 못했으면 model 이 None 이고 reasons 가 찬다."""
    model: ThermalModel | None
    reasons: list[str]
    diagnostics: dict


def assess(samples: list[tuple[datetime, float, int]]) -> list[str]:
    """자료가 a·b 를 분리하기에 충분한지 본다. 부족한 이유들을 돌려준다."""
    reasons = []
    if len(samples) < MIN_SAMPLES:
        reasons.append(f"표본이 {len(samples)}개뿐입니다 (최소 {MIN_SAMPLES}).")
        return reasons

    temps = [t for _, t, _ in samples]
    spread = max(temps) - min(temps)
    if spread < MIN_TEMP_RANGE_C:
        reasons.append(
            f"온도 변화폭이 {spread:.2f}℃ 뿐입니다 (최소 {MIN_TEMP_RANGE_C}℃). "
            "열적 여기가 없어 시정수를 잴 수 없습니다.")

    n_cool = sum(1 for _, _, u in samples if u)
    n_idle = len(samples) - n_cool
    if n_cool < MIN_COOLING_SAMPLES:
        reasons.append(
            f"냉방 가동 구간 표본이 {n_cool}개입니다 (최소 {MIN_COOLING_SAMPLES}). "
            "냉각률 b 를 표류 d 와 분리할 수 없습니다.")
    if n_idle < MIN_IDLE_SAMPLES:
        reasons.append(
            f"냉방 정지 구간 표본이 {n_idle}개입니다 (최소 {MIN_IDLE_SAMPLES}).")
    return reasons


def identify(samples: list[tuple[datetime, float, int]],
             ridge: float = 1e-6) -> Identification:
    """(시각, 온도, 냉방여부) 에서 a, b, d 를 최소제곱으로 추정한다.

    회귀식:  dT/dt = -a·T + d + b·u
    설계행렬 X = [T, 1, u], 계수 = [-a, d, b]

    표본 간격이 일정하지 않으므로 dT/dt 는 이웃 차분으로 만들고, 간격이
    너무 벌어진 쌍(2분 초과)은 버린다. 그 사이에 무슨 일이 있었는지
    모르는 채로 기울기를 만들면 잡음을 신호로 배운다.
    """
    reasons = assess(samples)
    diagnostics: dict = {"n_samples": len(samples)}
    if reasons:
        return Identification(None, reasons, diagnostics)

    rows, ys = [], []
    for (t0, T0, u0), (t1, T1, _) in zip(samples, samples[1:]):
        dt = (t1 - t0).total_seconds() / 60.0
        if not (0 < dt <= 2.0):
            continue
        rows.append([T0, 1.0, float(u0)])
        ys.append((T1 - T0) / dt)

    diagnostics["n_pairs"] = len(rows)
    if len(rows) < MIN_SAMPLES:
        reasons.append(f"쓸 수 있는 인접 쌍이 {len(rows)}개뿐입니다.")
        return Identification(None, reasons, diagnostics)

    # 정규방정식 (X'X + λI) β = X'y — 3x3 이라 직접 푼다.
    k = 3
    XtX = [[sum(r[i] * r[j] for r in rows) + (ridge if i == j else 0.0)
            for j in range(k)] for i in range(k)]
    Xty = [sum(r[i] * y for r, y in zip(rows, ys)) for i in range(k)]

    # 가우스 소거
    M = [XtX[i][:] + [Xty[i]] for i in range(k)]
    for c in range(k):
        piv = max(range(c, k), key=lambda r: abs(M[r][c]))
        if abs(M[piv][c]) < 1e-12:
            reasons.append("설계행렬이 특이합니다 — 온도와 냉방 신호가 구분되지 않습니다.")
            return Identification(None, reasons, diagnostics)
        M[c], M[piv] = M[piv], M[c]
        for r in range(k):
            if r == c:
                continue
            f = M[r][c] / M[c][c]
            for j in range(c, k + 1):
                M[r][j] -= f * M[c][j]
    beta = [M[i][k] / M[i][i] for i in range(k)]

    a, d, b = -beta[0], beta[1], beta[2]

    mean_y = sum(ys) / len(ys)
    ss_tot = sum((y - mean_y) ** 2 for y in ys)
    ss_res = sum((y - sum(bi * ri for bi, ri in zip(beta, r))) ** 2
                 for r, y in zip(rows, ys))
    r2 = 1.0 - ss_res / ss_tot if ss_tot > 0 else 0.0
    diagnostics.update({"a": a, "b": b, "d": d, "r2": r2})

    # 부호가 물리와 어긋나면 받아들이지 않는다. a<=0 은 온도가 발산한다는
    # 뜻이고, b>=0 은 냉방을 켤수록 더워진다는 뜻이다.
    if a <= 0:
        reasons.append(f"시정수 계수 a={a:.5f} 가 양수가 아닙니다 — 발산하는 모델입니다.")
    if b >= 0:
        reasons.append(f"냉각률 b={b:+.5f} 가 음수가 아닙니다 — 냉방이 온도를 올린다는 결과입니다.")
    if r2 < MIN_R2:
        reasons.append(f"설명력 R²={r2:.3f} 가 낮습니다 (최소 {MIN_R2}).")
    if reasons:
        return Identification(None, reasons, diagnostics)

    model = ThermalModel(a=a, b=b, d=d, calibrated=True, r2=r2,
                         metadata={"n_pairs": len(rows),
                                   "identified_at": datetime.now().isoformat()})
    return Identification(model, [], diagnostics)
