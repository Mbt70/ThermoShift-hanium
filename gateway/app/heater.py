"""합성 재실자 — 히팅패드로 재실 열부하를 흉내 낸다.

왜 필요한가
-----------
목업이 20x20x30cm(12L) 라 사람을 넣을 수 없다. 그런데 재실 기반 제어를
검증하려면 "사람이 있을 때의 열부하" 가 있어야 한다. 12V 10W 히팅패드를
릴레이 duty 로 조절해 그 부하를 만든다.

duty 를 쓰는 이유는 두 가지다. 하나는 켜고 끄는 이진 열원보다 연속 가변
열원이 모델 식별에 훨씬 유리하다는 것. 다른 하나는 게이트웨이가 열원을
직접 지령하므로 **재실 인원의 정답을 우리가 안다**는 것이다. 실측 라벨이
없어 막혀 있던 모델 비교 작업이 여기서 풀린다.

스케일링 계약
-------------
W 를 부피비로 줄이면 1인 상당이 0.014W 가 되고 온도 변화가 0.016'C 라
측정이 불가능하다. 그래서 **W 가 아니라 온도 상승(dT)을 맞춘다.**

기준 공간을 60m3 강의실 / 정원 30명 / 1 ACH 로 잡으면 1인당 정상상태
온도 상승이 약 0.5K 다. 목업에서 같은 0.5K 를 만드는 전력이 1인 상당이다.

    P_1인 = PERSON_DELTA_T_K x UA_박스

이 계약은 가정이지 측정이 아니다. 발표·보고서에서는 "1인 상당"이 이
정의를 가리킨다는 것을 반드시 밝혀야 한다. 기준 공간을 바꾸면 숫자가
전부 바뀐다.

무엇이 검증되고 무엇이 안 되는가
--------------------------------
합성 재실자는 열과 CO2 를 서로 **독립된 장치**로 만든다. 실제 사람은 그
비율이 생리적으로 고정돼 있다. 따라서 이 장치로 검증되는 것은 추정기가
제대로 도는가(식별성·수렴·잡음 견딤)이지, 사람의 열:CO2 비율 가정이
맞는가가 아니다. 후자는 사람이 실제로 들어가 있는 세션으로 따로 확인해야
한다.

그리고 PIR 은 이 방식으로 대체할 수 없다. 감지 원뿔이 수 미터인 센서를
20cm 상자에 넣으면 벽으로 포화된다. 재실 '검출' 모델은 실제 공간에서
받은 자료로 검증한다. 목업에서는 재실이 미지수가 아니라 우리가 넣는
입력이므로, 여기서 하는 일은 재실 검출이 아니라 물리 식별이다.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, asdict
from pathlib import Path

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------
# 스케일링 계약. 바꾸면 "1인 상당" 의 뜻이 바뀐다.
# ---------------------------------------------------------------------
REFERENCE_ROOM_M3 = 60.0
REFERENCE_OCCUPANCY = 30
# 기준 공간에서 재실자 1명이 만드는 정상상태 온도 상승(K).
# 60m3 / 1 ACH / 1인 현열 70W 가정에서 나온 값이다.
PERSON_DELTA_T_K = 0.5

# ---------------------------------------------------------------------
# 목업 물리 상수. **교정 전 추정값이다.**
#
#   UA  0.7 W/K   실측 자연감쇠(-0.036'C/분, dT=2.5'C)로 얻은 tau=70분과
#                 벽체(아크릴 5mm, 0.32m2)에서 추정한 C=3000J/K 로 역산.
#   C   3000 J/K  공기는 14.5J/K 뿐이라 벽이 지배한다.
#
# 교정 절차는 CALIBRATION_GUIDE 참고. duty 100% 로 켜고 초기 기울기를
# 재면 C = P / (dT/dt) 가 바로 나오고, UA = C / tau 로 이어진다.
# ---------------------------------------------------------------------
DEFAULT_BOX_UA_W_PER_K = 0.7
DEFAULT_BOX_C_J_PER_K = 3000.0
DEFAULT_PAD_POWER_W = 10.0

# 안전 상한. 이 온도를 넘으면 duty 를 0 으로 내린다.
# 목업 재료(아크릴)와 패드 표면온도를 함께 고려한 값이다.
MAX_BOX_TEMP_C = 45.0

# 측정이 이 시간보다 오래되면 히터를 끈다. 온도를 모르는 채로 가열하는
# 것이 가장 위험하다 — 안전 차단이 판단 근거를 잃은 상태이기 때문이다.
MAX_TEMP_STALENESS_SEC = 120.0

PARAMS_PATH = Path("../ml/params/synthetic_occupant.json")

CALIBRATION_GUIDE = """\
합성 재실자 교정 절차 (약 40분, 1회)

  준비
    - 펠티어 방열면이 상자 **밖**에 있는지 확인한다. 안에 있으면 냉방의
      순효과가 가열이 되어 모든 측정이 무의미해진다.
    - 교반팬을 켜고 실험 내내 끄지 않는다. 단일 존 RC 모델은 상자 안이
      균일하다고 가정하는데, 점열원(패드)과 냉각판이 같이 있으면 공기가
      층을 이뤄 그 가정이 깨진다. 팬 발열은 상수라 d 항에 흡수된다.
    - 패드 저항을 재서 실제 전력을 확인한다. 12V 10W 면 14.4옴이다.

  1. duty 0 으로 20분  -> 표류 d 와 잡음 확인
  2. duty 100 으로 20분 -> 초기 기울기에서 C = P / (dT/dt)
  3. 다시 duty 0 으로 40분 -> 감쇠에서 tau, 그리고 UA = C / tau

  끝나면:  python -m ml.calibrate_synthetic_occupant
"""


@dataclass
class SyntheticOccupant:
    """duty(%) 와 재실 인원 상당을 오가는 환산기."""

    box_ua_w_per_k: float = DEFAULT_BOX_UA_W_PER_K
    box_c_j_per_k: float = DEFAULT_BOX_C_J_PER_K
    pad_power_w: float = DEFAULT_PAD_POWER_W
    # 실측으로 교정된 값인지. False 면 UI·보고서에 '가정값' 으로 표시한다.
    calibrated: bool = False

    @property
    def watts_per_person(self) -> float:
        """1인 상당의 전력(W). 스케일링 계약이 여기서 숫자가 된다."""
        return PERSON_DELTA_T_K * self.box_ua_w_per_k

    @property
    def max_occupants(self) -> float:
        """duty 100% 가 나타낼 수 있는 최대 인원 상당."""
        return self.pad_power_w / self.watts_per_person

    def duty_for_occupants(self, occupants: float) -> int:
        """재실 인원 상당 -> duty(%). 0~100 으로 자른다.

        정수로 반올림하는 이유는 노드가 정수 duty 만 받기 때문이다.
        10W 패드에서 1% 는 0.1W 이고 이는 약 0.3명 상당이라, 반올림 오차가
        분해능보다 작다.
        """
        if occupants <= 0:
            return 0
        watts = occupants * self.watts_per_person
        duty = round(100.0 * watts / self.pad_power_w)
        return max(0, min(100, int(duty)))

    def occupants_for_duty(self, duty_pct: float) -> float:
        """duty(%) -> 재실 인원 상당. 기록에 정답 라벨로 남길 값이다."""
        watts = self.pad_power_w * duty_pct / 100.0
        return watts / self.watts_per_person

    def to_json(self, path: Path = PARAMS_PATH) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(asdict(self), indent=2), encoding="utf-8")

    @classmethod
    def load(cls, path: Path = PARAMS_PATH) -> "SyntheticOccupant":
        """교정값이 있으면 쓰고, 없으면 추정값으로 돈다.

        ml 을 import 하지 않는다. 게이트웨이는 cwd=gateway/ 로 도는데
        ml 패키지는 그 밖에 있어서, import 하면 배포 형태에 묶인다.
        """
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            logger.info(
                "합성 재실자 교정값이 없어 추정값으로 돕니다 (%s). "
                "duty-인원 환산은 가정값입니다.", path,
            )
            return cls()
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("합성 재실자 교정값을 읽지 못했습니다 (%s): %s", path, exc)
            return cls()
        return cls(**data)


def safe_duty(
    requested_duty: int,
    temperature_c: float | None,
    temp_age_sec: float | None,
    max_temp_c: float = MAX_BOX_TEMP_C,
) -> tuple[int, str | None]:
    """안전 차단을 통과한 duty 와, 잘렸다면 그 이유를 돌려준다.

    순수 함수로 둔 이유는 이 판단이 시험 가능해야 하기 때문이다. 무인으로
    밤새 가열하는 장치라 여기가 틀리면 되돌릴 방법이 없다.

    막는 것은 세 가지다.
      - 온도를 모를 때 (센서 없음/정지)  : 안전 차단이 근거를 잃은 상태다
      - 측정이 오래됐을 때               : 위와 같다
      - 상한 온도를 넘었을 때
    """
    if requested_duty <= 0:
        return 0, None

    if temperature_c is None:
        return 0, "온도를 알 수 없어 히터를 차단했습니다"

    if temp_age_sec is not None and temp_age_sec > MAX_TEMP_STALENESS_SEC:
        return 0, (
            f"온도 측정이 {temp_age_sec:.0f}초 전 값이라 히터를 차단했습니다 "
            f"(상한 {MAX_TEMP_STALENESS_SEC:.0f}초)"
        )

    if temperature_c >= max_temp_c:
        return 0, (
            f"{temperature_c:.1f}'C 로 안전 상한 {max_temp_c:.1f}'C 에 닿아 "
            f"히터를 차단했습니다"
        )

    return max(0, min(100, int(requested_duty))), None


class HeaterController:
    """히터 duty 를 노드로 내보내고 안전 차단을 적용한다.

    발행 주기에 대해: duty 가 그대로여도 **매 판단 주기마다 보낸다.**
    노드의 워치독(HEATER_COMMAND_TIMEOUT_MS, 120초)이 이 발행을 먹고
    산다. 값이 바뀔 때만 보내면, 게이트웨이가 멀쩡한데도 노드가 명령이
    끊긴 줄 알고 히터를 꺼 버린다. 반대로 게이트웨이가 죽으면 발행이
    멈추고 노드가 알아서 끈다 — 그러라고 만든 구조다.
    """

    # 같은 차단 사유를 이 간격으로만 로그에 남긴다.
    BLOCK_LOG_INTERVAL_SEC = 300.0

    def __init__(self, publish_func, topic: str,
                 scale: "SyntheticOccupant | None" = None):
        self.publish_func = publish_func
        self.topic = topic
        self.scale = scale if scale is not None else SyntheticOccupant.load()
        self.requested_duty = 0
        self.applied_duty = 0
        self._last_block_reason: str | None = None
        self._last_block_log_at: float = 0.0
        # 직전 tick 에서 안전 차단이 걸렸다면 그 사유. 기록에 남긴다 —
        # 지령과 실제가 다른 구간은 분석에서 따로 봐야 한다.
        self.last_block_reason: str | None = None

    def request_occupants(self, occupants: float) -> int:
        """재실 인원 상당으로 지령한다. 실제로 적용되는 값은 tick 이 정한다."""
        self.requested_duty = self.scale.duty_for_occupants(occupants)
        return self.requested_duty

    def request_duty(self, duty_pct: int) -> int:
        self.requested_duty = max(0, min(100, int(duty_pct)))
        return self.requested_duty

    @property
    def applied_occupants(self) -> float:
        """지금 실제로 걸려 있는 열부하의 인원 상당. 정답 라벨로 기록한다."""
        return self.scale.occupants_for_duty(self.applied_duty)

    def tick(self, temperature_c: float | None,
             temp_age_sec: float | None = None) -> int:
        import time

        duty, reason = safe_duty(self.requested_duty, temperature_c, temp_age_sec)
        self.last_block_reason = reason

        if reason is not None:
            now = time.monotonic()
            if (reason != self._last_block_reason
                    or now - self._last_block_log_at >= self.BLOCK_LOG_INTERVAL_SEC):
                logger.warning("히터 차단: %s", reason)
                self._last_block_reason = reason
                self._last_block_log_at = now
        else:
            self._last_block_reason = None

        if duty != self.applied_duty:
            logger.info(
                "히터 duty %d%% -> %d%% (재실 %0.1f명 상당)",
                self.applied_duty, duty, self.scale.occupants_for_duty(duty),
            )
        self.applied_duty = duty

        # 값이 그대로여도 매번 보낸다. 위 docstring 참고.
        self.publish_func(self.topic, str(duty))
        return duty
