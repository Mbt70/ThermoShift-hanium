"""게이트웨이가 쓰는 열모델 로더.

ml/thermal_model.py 는 학습·식별용이라 게이트웨이가 직접 임포트하지 않는다
(게이트웨이는 gateway/ 를 작업 디렉터리로 돌아서 저장소 뿌리가 sys.path 에
없다). 대신 ml/train_thermal.py 가 떨궈 둔 JSON 을 읽어 예측에 필요한 최소
기능만 제공한다.

파일이 없으면 None 을 돌려준다. 그러면 정책이 예냉을 하지 않는다 —
리드타임을 모르는 채로 냉방을 미리 켜면 몇 시간씩 헛돌 수 있기 때문이다.
"""

import json
import logging
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

PARAM_PATH = Path(__file__).resolve().parents[2] / "ml" / "params" / "thermal.json"


@dataclass
class ThermalModel:
    a: float          # 1/분, 시정수의 역수
    b: float          # ℃/분, 냉방 냉각률 (음수)
    d: float          # ℃/분, 외기·내부발열 표류
    calibrated: bool = False

    def steady_state(self, cooling: bool) -> float:
        return (self.d + (self.b if cooling else 0.0)) / self.a

    def predict(self, t0_c: float, minutes: float, cooling: bool) -> float:
        inf = self.steady_state(cooling)
        return inf + (t0_c - inf) * math.exp(-self.a * minutes)

    def lead_time_minutes(self, t0_c: float, target_c: float,
                          cap_minutes: float = 180.0) -> Optional[float]:
        """target_c 에 닿기까지 냉방을 몇 분 돌려야 하는지. 못 닿으면 None."""
        if t0_c <= target_c:
            return 0.0
        inf = self.steady_state(cooling=True)
        if inf >= target_c:
            return None
        ratio = (target_c - inf) / (t0_c - inf)
        if ratio <= 0:
            return None
        return min(-math.log(ratio) / self.a, cap_minutes)


def load_thermal_model() -> Optional[ThermalModel]:
    if not PARAM_PATH.is_file():
        logger.info("열모델 파라미터가 없습니다 (%s) — 예냉을 사용하지 않습니다",
                    PARAM_PATH.name)
        return None
    try:
        d = json.loads(PARAM_PATH.read_text())
        m = ThermalModel(a=d["a"], b=d["b"], d=d["d"],
                         calibrated=bool(d.get("calibrated")))
    except (json.JSONDecodeError, KeyError, TypeError) as exc:
        logger.warning("열모델 파라미터를 읽지 못했습니다 (%s) — 예냉 없이 동작", exc)
        return None
    if m.a <= 0:
        logger.warning("열모델 a=%.5f 가 유효하지 않습니다 — 예냉 없이 동작", m.a)
        return None
    logger.info("열모델 적용: 시정수 %.0f분, 냉각률 %+.3f℃/분 (%s)",
                1 / m.a, m.b, "교정됨" if m.calibrated else "가정값")
    return m
