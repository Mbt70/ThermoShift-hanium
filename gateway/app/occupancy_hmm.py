"""재실 추정 HMM — 학습된 파라미터를 읽어 쓰는 온라인 필터.

바뀐 점
-------
전이확률과 관측 우도가 코드에 박혀 있었다. 이제 ml/params/occupancy.json 이
있으면 그것을 쓰고, 없으면 config.yaml 의 전이행렬 + 아래 기본 우도로
그대로 동작한다. 학습이 필수 경로가 되면 안 되기 때문이다.

파일에는 이산화 경계(bins)까지 함께 들어 있다. 학습 때와 추론 때 관측을
같은 규칙으로 만들어야 확률이 같은 뜻을 갖는다.

없앤 것
-------
예전 코드에는 PIR 이 잡히면 사후확률을 [0.01, 0.04, 0.95] 로 통째 덮어쓰는
줄이 있었다. 베이즈 갱신을 무시하는 처리라, 수기 우도(P(PIR|OCCUPIED)=0.68)
가 약해서 필터가 재실 쪽으로 못 가던 것을 손으로 밀어 준 셈이었다. 학습된
우도는 0.86 대 0.007 로 갈라지므로 필터가 스스로 간다. 덮어쓰기를 두면
'PIR 이 한 번 튀면 무조건 재실' 이 되어 오검출을 그대로 받는다.
"""

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from app.config import get_config
from app.storage import get_storage

logger = logging.getLogger(__name__)

S_EMPTY, S_TRANSITION, S_OCCUPIED = 0, 1, 2
STATE_NAMES = ("EMPTY", "TRANSITION", "OCCUPIED")

# 학습 결과 파일. gateway/app/ 에서 두 단계 위가 저장소 뿌리다.
PARAM_PATH = Path(__file__).resolve().parents[2] / "ml" / "params" / "occupancy.json"

# 학습 파일이 없을 때 쓰는 값. ml/occupancy_model.PRIOR_EMISSION 과 같다
# (그쪽에서는 이것이 사전분포의 평균이다).
FALLBACK = {
    "pir": [0.032, 0.500, 0.679],
    "door": [0.200, 0.487, 0.310],
    "co2_slope": [[0.455, 0.505, 0.040],
                  [0.262, 0.476, 0.262],
                  [0.116, 0.465, 0.419]],
    "co2_delta": [[0.455, 0.455, 0.091],
                  [0.377, 0.377, 0.245],
                  [0.351, 0.351, 0.298]],
    "bins": {"co2_slope": [-3.0, 6.0], "co2_delta": [100.0, 250.0]},
}

# 상태 판정 기준. 확률 하나로 바로 뒤집지 않고 여유를 둔다(히스테리시스).
ENTER_OCCUPIED_P = 0.60      # 이 확률을 넘고
ENTER_OCCUPIED_TICKS = 2     # 이만큼 연속돼야 재실로 본다
ENTER_EMPTY_P = 0.70         # 공실은 더 확실할 때만 — 잘못 끄면 사람이 덥다


class OccupancyHMM:
    def __init__(self):
        self.config = get_config()
        self.storage = get_storage()

        self.params, self.source = self._load_params()
        self.transition = self.params["transition"]

        self.probs: List[float] = list(self.params.get("initial", [1/3, 1/3, 1/3]))
        self.state = "UNKNOWN"
        self.consecutive_occupied = 0
        self.last_update = datetime.now(timezone.utc)
        self.reasons: List[str] = []
        self.last_estimate_id: Optional[int] = None

        logger.info("재실 HMM 파라미터: %s", self.source)

    # ---------------- 파라미터 ----------------
    def _load_params(self) -> Tuple[Dict[str, Any], str]:
        if PARAM_PATH.is_file():
            try:
                data = json.loads(PARAM_PATH.read_text())
                meta = data.get("metadata", {})
                return data, (
                    f"학습값 {PARAM_PATH.name} "
                    f"(관측 {meta.get('observed_hours', '?')}시간, "
                    f"학습시각 {meta.get('trained_at', '?')})")
            except (json.JSONDecodeError, KeyError) as exc:
                # 깨진 파일 때문에 게이트웨이가 멈추면 안 된다. 기본값으로 간다.
                logger.warning("파라미터 파일을 읽지 못했습니다 (%s) — 기본값 사용", exc)

        params = dict(FALLBACK)
        params["transition"] = self.config.hmm.transition_matrix_30s
        params["initial"] = [1/3, 1/3, 1/3]
        return params, "기본값 (config.yaml 전이행렬 + 내장 우도)"

    @property
    def is_trained(self) -> bool:
        return self.source.startswith("학습값")

    # ---------------- 관측 ----------------
    def _encode(self, f: Dict[str, Any]) -> Dict[str, Optional[int]]:
        """피처를 관측 기호로. ml.occupancy_model.encode_values 와 같은 규칙.

        결측을 0 으로 채우지 않는 것이 핵심이다. 재실 센서가 끊긴 것과
        '움직임이 없다' 는 다른 사건인데, 0 으로 채우면 둘이 같아진다.
        """
        bins = self.params.get("bins", FALLBACK["bins"])

        def bucket(value, edges):
            if value is None:
                return None
            for i, edge in enumerate(edges):
                if value < edge:
                    return i
            return len(edges)

        occ_fresh = f.get("occ_fresh", True)
        return {
            "pir": int(bool(f["pir_recent"])) if occ_fresh else None,
            "door": int(bool(f["door_recent"])) if occ_fresh else None,
            "co2_slope": bucket(f.get("co2_slope_5m"), bins["co2_slope"]),
            "co2_delta": bucket(f.get("co2_delta_baseline"), bins["co2_delta"]),
        }

    def _likelihood(self, obs: Dict[str, Optional[int]]) -> List[float]:
        p = self.params
        out = [1.0, 1.0, 1.0]
        for s in range(3):
            if obs["pir"] is not None:
                out[s] *= p["pir"][s] if obs["pir"] else (1.0 - p["pir"][s])
            if obs["door"] is not None:
                out[s] *= p["door"][s] if obs["door"] else (1.0 - p["door"][s])
            if obs["co2_slope"] is not None:
                out[s] *= p["co2_slope"][s][obs["co2_slope"]]
            if obs["co2_delta"] is not None:
                out[s] *= p["co2_delta"][s][obs["co2_delta"]]
        return out

    def _explain(self, f: Dict[str, Any], obs: Dict[str, Optional[int]]) -> None:
        if obs["pir"] is None:
            self.reasons.append("재실 센서 신호 없음 — PIR·문 근거 제외")
        elif obs["pir"]:
            self.reasons.append(f"{int(f['pir_age_sec'])}초 전 움직임 감지")
        if obs["door"]:
            self.reasons.append(f"{int(f['door_age_sec'])}초 전 문 여닫힘")
        slope = f.get("co2_slope_5m")
        if obs["co2_slope"] == 2:
            self.reasons.append(f"CO2 상승 {slope:.1f}ppm/분")
        elif obs["co2_slope"] == 0:
            self.reasons.append(f"CO2 하강 {slope:.1f}ppm/분")
        delta = f.get("co2_delta_baseline")
        if delta is None:
            self.reasons.append("CO2 기준선 미확보 — 초과량 근거 제외")
        elif obs["co2_delta"] == 2:
            self.reasons.append(f"CO2 기준선 대비 +{delta:.0f}ppm")

    # ---------------- 갱신 ----------------
    def update(self, features: Dict[str, Any]) -> Tuple[str, List[float], List[str]]:
        self.reasons = []
        obs = self._encode(features)

        # 예측: 전이행렬로 사전확률을 민다.
        prior = [sum(self.probs[i] * self.transition[i][j] for i in range(3))
                 for j in range(3)]
        # 갱신: 관측 우도를 곱하고 정규화한다.
        L = self._likelihood(obs)
        post = [prior[i] * L[i] for i in range(3)]
        total = sum(post)
        self.probs = ([p / total for p in post] if total > 0
                      else [1/3, 1/3, 1/3])

        self._explain(features, obs)
        p_emp, _, p_occ = self.probs
        self.reasons.append(f"재실 확률 {p_occ:.2f}")

        self.consecutive_occupied = (
            self.consecutive_occupied + 1 if p_occ >= ENTER_OCCUPIED_P else 0)

        if self.consecutive_occupied >= ENTER_OCCUPIED_TICKS:
            new_state = "OCCUPIED"
        elif (p_emp >= ENTER_EMPTY_P
              and features["pir_age_sec"] >= self.config.control.empty_confirmation_sec):
            new_state = "EMPTY"
        else:
            new_state = "TRANSITION"

        # 재실 센서가 끊긴 채로 공실을 선언하면, 사람이 있는데 냉방이 꺼진다.
        if not features.get("occ_fresh", True) and new_state == "EMPTY":
            new_state = "TRANSITION"
            self.reasons.append("재실 센서 신호 없음 — 공실 판정 보류")

        self.state = new_state
        self.last_update = datetime.now(timezone.utc)

        self.last_estimate_id = self.storage.insert_occupancy_estimate(
            self.last_update.isoformat(),
            self.probs[S_EMPTY], self.probs[S_TRANSITION], self.probs[S_OCCUPIED],
            self.state, "OK" if features.get("occ_fresh", True) else "STALE",
            self.reasons)

        return self.state, self.probs, self.reasons


_hmm_instance = None


def get_occupancy_hmm() -> OccupancyHMM:
    global _hmm_instance
    if _hmm_instance is None:
        _hmm_instance = OccupancyHMM()
    return _hmm_instance
