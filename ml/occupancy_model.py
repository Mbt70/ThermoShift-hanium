"""재실 추정 HMM — 파라미터를 실측으로 추정할 수 있는 형태.

기존 gateway/app/occupancy_hmm.py 는 전이확률과 관측 우도가 **전부 코드에
박힌 상수**였다. 값 자체는 그럴듯했지만 근거가 없었고, 데이터가 쌓여도
좋아지지 않았다. 여기서는 같은 구조를 유지하되 파라미터를 추정 대상으로
바꾼다.

구조
----
상태 3개: EMPTY(0) → TRANSITION(1) → OCCUPIED(2)
관측은 네 갈래를 상태가 주어졌을 때 서로 독립이라고 본다.

    pir_recent    Bernoulli
    door_recent   Bernoulli
    co2_slope     3구간 (하강/평탄/상승)
    co2_delta     3구간 (낮음/중간/높음)

완전한 결합분포를 쓰지 않고 쪼갠 이유는 표본이다. 결합으로 두면 상태당
2*2*3*3=36 칸을 채워야 하는데 지금 있는 에폭은 수백 개뿐이라 대부분이
빈칸이 된다.

왜 순수 EM 이 아니라 MAP-EM 인가
--------------------------------
지금 쓸 수 있는 실측은 3.25시간(390에폭)이고 라벨이 없다. 이 양으로 순수
Baum-Welch 를 돌리면 상태의 뜻이 뒤집히거나(EMPTY 가 재실을 가리키는 식)
자기전이확률이 1.0 으로 붙어 버린다. 그래서 기존 수기 상수를 **사전분포의
평균**으로 삼고 데이터가 그것을 밀어내게 한다. 데이터가 적으면 기존 값
근처에 머물고, 3~4일치가 쌓이면 그만큼 데이터 쪽으로 움직인다. 재학습은
같은 명령을 다시 돌리기만 하면 된다.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from pathlib import Path

STATES = ("EMPTY", "TRANSITION", "OCCUPIED")
N = 3

# --- 관측 이산화 경계 -------------------------------------------------
# 이 값들은 파라미터 파일에 함께 저장된다. 게이트웨이가 파일만 읽고도
# 학습 때와 똑같이 관측을 만들 수 있어야 하기 때문이다. 학습과 추론의
# 경계가 어긋나면 배운 확률이 다른 뜻이 된다.
DEFAULT_BINS = {
    # ppm/분 — 이보다 가파르게 떨어지면 '하강', 올라가면 '상승'
    "co2_slope": [-3.0, 6.0],
    # ppm — 기준선 대비 초과량
    "co2_delta": [100.0, 250.0],
}

# --- 사전분포 평균 ----------------------------------------------------
# 기존 occupancy_hmm._get_observation_likelihoods 의 상수를 상태별로
# 정규화해 확률로 바꾼 값이다. 예를 들어 PIR 은 감지 0.03 / 미감지 0.90
# (EMPTY 기준)이었으므로 P(pir=1|EMPTY) = 0.03/(0.03+0.90) = 0.032 이 된다.
PRIOR_EMISSION = {
    "pir":       [0.032, 0.500, 0.679],                 # P(pir_recent=1 | s)
    "door":      [0.200, 0.487, 0.310],                 # P(door_recent=1 | s)
    "co2_slope": [[0.455, 0.505, 0.040],                # EMPTY  [하강,평탄,상승]
                  [0.262, 0.476, 0.262],                # TRANSITION
                  [0.116, 0.465, 0.419]],               # OCCUPIED
    "co2_delta": [[0.455, 0.455, 0.091],                # EMPTY  [낮음,중간,높음]
                  [0.377, 0.377, 0.245],
                  [0.351, 0.351, 0.298]],
}

# config.yaml 의 30초 전이행렬. 사전분포 평균으로 쓴다.
PRIOR_TRANSITION = [
    [0.985, 0.014, 0.001],
    [0.100, 0.600, 0.300],
    [0.003, 0.027, 0.970],
]

# 사전분포의 세기(가상 관측 수). 클수록 기존 값에서 덜 움직인다.
#
# 전이확률을 훨씬 강하게 잡는 이유: 자기전이 0.985 는 "평균 33분 머문다"는
# 뜻인데, 3시간짜리 기록으로는 그 길이를 잴 수가 없다. 관측이 며칠분
# 쌓이기 전까지는 이 값을 데이터가 흔들도록 두면 안 된다.
PRIOR_STRENGTH_TRANSITION = 400.0
PRIOR_STRENGTH_EMISSION = 40.0


# =====================================================================
def encode(epoch) -> dict:
    """에폭 하나를 관측 기호로 바꾼다. 관측이 없는 갈래는 None(결측).

    epoch 는 ml.dataset.Epoch 이거나, 같은 이름의 속성을 가진 무엇이든 된다.
    """
    return encode_values(
        pir_recent=epoch.pir_recent,
        door_recent=epoch.door_recent,
        co2_slope=epoch.co2_slope_5m,
        co2_delta=epoch.co2_delta_baseline,
        occ_fresh=epoch.occ_fresh,
        co2_present=epoch.co2 is not None,
    )


def encode_values(*, pir_recent, door_recent, co2_slope, co2_delta,
                  occ_fresh=True, co2_present=True, bins=None) -> dict:
    """게이트웨이도 이 함수와 같은 규칙을 써야 한다.

    결측을 0 으로 채우지 않는 것이 중요하다. 재실 센서가 끊긴 것과 '사람이
    없다' 는 전혀 다른 사건인데, 0 으로 채우면 둘이 같아진다.
    """
    b = bins or DEFAULT_BINS

    def bucket(value, edges):
        if value is None:
            return None
        for i, edge in enumerate(edges):
            if value < edge:
                return i
        return len(edges)

    return {
        # 재실 센서가 끊겼으면 PIR·문 관측은 없는 것으로 둔다.
        "pir": int(bool(pir_recent)) if occ_fresh else None,
        "door": int(bool(door_recent)) if occ_fresh else None,
        "co2_slope": bucket(co2_slope, b["co2_slope"]) if co2_present else None,
        "co2_delta": bucket(co2_delta, b["co2_delta"]),
    }


# =====================================================================
@dataclass
class OccupancyModel:
    initial: list[float] = field(default_factory=lambda: [1 / 3] * N)
    transition: list[list[float]] = field(
        default_factory=lambda: [row[:] for row in PRIOR_TRANSITION])
    pir: list[float] = field(
        default_factory=lambda: PRIOR_EMISSION["pir"][:])
    door: list[float] = field(
        default_factory=lambda: PRIOR_EMISSION["door"][:])
    co2_slope: list[list[float]] = field(
        default_factory=lambda: [r[:] for r in PRIOR_EMISSION["co2_slope"]])
    co2_delta: list[list[float]] = field(
        default_factory=lambda: [r[:] for r in PRIOR_EMISSION["co2_delta"]])
    bins: dict = field(default_factory=lambda: {k: v[:] for k, v in DEFAULT_BINS.items()})
    metadata: dict = field(default_factory=dict)

    # ---------------- 관측 우도 ----------------
    def likelihood(self, obs: dict) -> list[float]:
        """상태별 P(관측 | 상태). 결측 갈래는 1 을 곱해 영향이 없게 한다."""
        out = [1.0] * N
        for s in range(N):
            if obs["pir"] is not None:
                p = self.pir[s]
                out[s] *= p if obs["pir"] else (1.0 - p)
            if obs["door"] is not None:
                p = self.door[s]
                out[s] *= p if obs["door"] else (1.0 - p)
            if obs["co2_slope"] is not None:
                out[s] *= self.co2_slope[s][obs["co2_slope"]]
            if obs["co2_delta"] is not None:
                out[s] *= self.co2_delta[s][obs["co2_delta"]]
        return out

    # ---------------- 전방-후방 ----------------
    def forward_backward(self, observations: list[dict]):
        """스케일링된 전방-후방. (감마, 크시, 로그우도) 를 돌려준다.

        스케일링을 쓰는 이유는 단순하다. 에폭이 수백 개만 돼도 확률의 곱이
        배정밀도 하한 아래로 내려가 전부 0 이 된다.
        """
        T = len(observations)
        if T == 0:
            return [], [], 0.0

        B = [self.likelihood(o) for o in observations]
        alpha = [[0.0] * N for _ in range(T)]
        scale = [0.0] * T

        for s in range(N):
            alpha[0][s] = self.initial[s] * B[0][s]
        scale[0] = sum(alpha[0]) or 1e-300
        alpha[0] = [a / scale[0] for a in alpha[0]]

        for t in range(1, T):
            for j in range(N):
                alpha[t][j] = B[t][j] * sum(
                    alpha[t - 1][i] * self.transition[i][j] for i in range(N))
            scale[t] = sum(alpha[t]) or 1e-300
            alpha[t] = [a / scale[t] for a in alpha[t]]

        beta = [[1.0] * N for _ in range(T)]
        for t in range(T - 2, -1, -1):
            for i in range(N):
                beta[t][i] = sum(
                    self.transition[i][j] * B[t + 1][j] * beta[t + 1][j]
                    for j in range(N)) / scale[t + 1]

        gamma = []
        for t in range(T):
            g = [alpha[t][i] * beta[t][i] for i in range(N)]
            z = sum(g) or 1e-300
            gamma.append([x / z for x in g])

        xi = []
        for t in range(T - 1):
            m = [[alpha[t][i] * self.transition[i][j] * B[t + 1][j] * beta[t + 1][j]
                  for j in range(N)] for i in range(N)]
            z = sum(sum(r) for r in m) or 1e-300
            xi.append([[v / z for v in r] for r in m])

        loglik = sum(math.log(s) for s in scale)
        return gamma, xi, loglik

    def loglikelihood(self, sequences: list[list[dict]]) -> float:
        return sum(self.forward_backward(seq)[2] for seq in sequences if seq)

    # ---------------- 온라인 추론 (게이트웨이와 같은 계산) ----------------
    def filter_step(self, probs: list[float], obs: dict) -> list[float]:
        prior = [sum(probs[i] * self.transition[i][j] for i in range(N))
                 for j in range(N)]
        L = self.likelihood(obs)
        post = [prior[i] * L[i] for i in range(N)]
        z = sum(post)
        return [p / z for p in post] if z > 0 else [1 / 3] * N

    # ---------------- 직렬화 ----------------
    def to_dict(self) -> dict:
        return {
            "states": list(STATES), "initial": self.initial,
            "transition": self.transition, "pir": self.pir, "door": self.door,
            "co2_slope": self.co2_slope, "co2_delta": self.co2_delta,
            "bins": self.bins, "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "OccupancyModel":
        return cls(initial=d["initial"], transition=d["transition"],
                   pir=d["pir"], door=d["door"], co2_slope=d["co2_slope"],
                   co2_delta=d["co2_delta"],
                   bins=d.get("bins", {k: v[:] for k, v in DEFAULT_BINS.items()}),
                   metadata=d.get("metadata", {}))

    def save(self, path: str | Path) -> None:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(self.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")

    @classmethod
    def load(cls, path: str | Path) -> "OccupancyModel":
        return cls.from_dict(json.loads(Path(path).read_text(encoding="utf-8")))


# =====================================================================
def baum_welch_map(sequences: list[list[dict]], *, iterations: int = 200,
                   tol: float = 1e-6,
                   strength_transition: float = PRIOR_STRENGTH_TRANSITION,
                   strength_emission: float = PRIOR_STRENGTH_EMISSION,
                   init: OccupancyModel | None = None
                   ) -> tuple[OccupancyModel, list[float]]:
    """사전분포를 넣은 Baum-Welch. (모델, 반복별 로그우도) 를 돌려준다.

    M-단계에서 기대 빈도에 사전분포의 가상 관측수를 더한다(디리클레/베타
    켤레사전). 데이터가 많아질수록 가상 관측의 비중이 자동으로 줄어든다.
    """
    model = init or OccupancyModel()
    sequences = [s for s in sequences if len(s) >= 2]
    if not sequences:
        raise ValueError("학습할 시퀀스가 없습니다")

    # 사전 가상 관측수 (평균 × 세기)
    a_prior = [[PRIOR_TRANSITION[i][j] * strength_transition for j in range(N)]
               for i in range(N)]
    pir_prior = [(PRIOR_EMISSION["pir"][s] * strength_emission,
                  (1 - PRIOR_EMISSION["pir"][s]) * strength_emission)
                 for s in range(N)]
    door_prior = [(PRIOR_EMISSION["door"][s] * strength_emission,
                   (1 - PRIOR_EMISSION["door"][s]) * strength_emission)
                  for s in range(N)]
    slope_prior = [[PRIOR_EMISSION["co2_slope"][s][k] * strength_emission
                    for k in range(3)] for s in range(N)]
    delta_prior = [[PRIOR_EMISSION["co2_delta"][s][k] * strength_emission
                    for k in range(3)] for s in range(N)]

    history: list[float] = []
    for _ in range(iterations):
        a_num = [[a_prior[i][j] for j in range(N)] for i in range(N)]
        init_num = [1.0] * N
        pir_num = [[pir_prior[s][0], pir_prior[s][1]] for s in range(N)]
        door_num = [[door_prior[s][0], door_prior[s][1]] for s in range(N)]
        slope_num = [slope_prior[s][:] for s in range(N)]
        delta_num = [delta_prior[s][:] for s in range(N)]
        total_ll = 0.0

        for seq in sequences:
            gamma, xi, ll = model.forward_backward(seq)
            total_ll += ll
            for s in range(N):
                init_num[s] += gamma[0][s]
            for t, x in enumerate(xi):
                for i in range(N):
                    for j in range(N):
                        a_num[i][j] += x[i][j]
            for t, obs in enumerate(seq):
                for s in range(N):
                    g = gamma[t][s]
                    if obs["pir"] is not None:
                        pir_num[s][0 if obs["pir"] else 1] += g
                    if obs["door"] is not None:
                        door_num[s][0 if obs["door"] else 1] += g
                    if obs["co2_slope"] is not None:
                        slope_num[s][obs["co2_slope"]] += g
                    if obs["co2_delta"] is not None:
                        delta_num[s][obs["co2_delta"]] += g

        norm = lambda v: [x / sum(v) for x in v]
        model.initial = norm(init_num)
        model.transition = [norm(row) for row in a_num]
        model.pir = [pir_num[s][0] / (pir_num[s][0] + pir_num[s][1]) for s in range(N)]
        model.door = [door_num[s][0] / (door_num[s][0] + door_num[s][1]) for s in range(N)]
        model.co2_slope = [norm(slope_num[s]) for s in range(N)]
        model.co2_delta = [norm(delta_num[s]) for s in range(N)]

        history.append(total_ll)
        if len(history) >= 2 and abs(history[-1] - history[-2]) < tol:
            break

    return model, history


def check_identifiability(model: OccupancyModel) -> list[str]:
    """상태의 뜻이 뒤집히지 않았는지 본다.

    EM 은 상태에 이름을 붙여 주지 않는다. 사전분포가 순서를 잡아 주도록
    설계했지만, 데이터가 세지면 뒤집힐 수 있다. 뒤집힌 모델을 그대로
    배포하면 '사람이 있을 때 냉방을 끄는' 제어가 된다.
    """
    warns = []
    if not (model.pir[0] < model.pir[1] < model.pir[2]):
        warns.append(
            f"P(PIR|상태) 순서가 EMPTY<TRANSITION<OCCUPIED 가 아닙니다: "
            f"{[round(p, 3) for p in model.pir]} — 상태 해석이 뒤집혔을 수 있습니다.")
    # CO2 초과는 재실에서 가장 흔해야 한다. 그렇지 않으면 그 갈래가 재실을
    # 거꾸로 가리키게 되므로, 세 상태 중 최댓값이 OCCUPIED 인지로 본다.
    high = [model.co2_delta[s][2] for s in range(N)]
    if high.index(max(high)) != 2:
        warns.append(
            f"CO2 초과(높음) 확률이 {STATES[high.index(max(high))]} 에서 가장 큽니다 "
            f"(EMPTY {high[0]:.3f} / TRANSITION {high[1]:.3f} / OCCUPIED {high[2]:.3f}) "
            "— CO2 근거가 재실을 거꾸로 가리킵니다.")

    # CO2 상승도 마찬가지다. 사람이 있어야 CO2 가 오른다.
    rise = [model.co2_slope[s][2] for s in range(N)]
    if rise.index(max(rise)) != 2:
        warns.append(
            f"CO2 상승 확률이 {STATES[rise.index(max(rise))]} 에서 가장 큽니다 "
            f"(EMPTY {rise[0]:.3f} / TRANSITION {rise[1]:.3f} / OCCUPIED {rise[2]:.3f}) "
            "— 환기로 CO2 가 떨어지는 동안 사람이 있던 구간이 섞였을 수 있습니다.")
    for s, name in enumerate(STATES):
        if model.transition[s][s] > 0.999:
            warns.append(f"{name} 자기전이확률이 {model.transition[s][s]:.4f} 로 "
                         "1 에 붙었습니다 — 그 상태에서 빠져나오지 못합니다.")
    return warns
