"""가진(加振) 계획 — 열모델 식별을 위해 히터를 어떻게 흔들 것인가.

왜 그냥 켜 보면 안 되는가
-------------------------
히터를 한 번 켜고 온도가 오르는 것을 재면 될 것 같지만, 그 상승에는 히터
말고 외기 표류도 섞여 있다. 스텝 하나로는 둘을 나눌 수 없다. 그래서 켜고
끄기를 **여러 번** 넣어, 히터에만 동기화된 성분을 뽑아내야 한다.

시간이 없을 때 무엇을 포기하는가
--------------------------------
목업의 열 시정수는 약 70분이다. 교과서대로면 3~5 tau(3.5~6시간)를 흔들어야
하지만, 그만한 시간을 낼 수 없는 경우가 보통이다. 그럴 때 세 계수를
**같은 실험에서 다 뽑으려 하지 않는 것**이 요령이다.

    c = P/C   (히터 감도)   짧고 센 스텝이면 충분하다. 초기 기울기가 곧 답이다.
    d         (표류)        가열 전 정지 구간 10분이면 잡힌다.
    a = UA/C  (1/시정수)    본래 긴 자료가 필요하다. 그런데 이건 **아무도
                            지키지 않아도 쌓인다** — 평소 운전 기록의 무가진
                            구간이 전부 감쇠 자료다.

즉 사람이 붙어 있어야 하는 것은 c 와 d 뿐이고, 45분이면 된다. a 는 며칠에
걸쳐 저절로 정밀해진다.

다행히 잡음이 아주 낮아서(sigma=0.016'C) 짧은 창에서도 신호가 크다. 100%
스텝 15분이면 상승이 약 2.7'C, 이어지는 20분 감쇠에서 0.68'C 가 꺾이는데
이는 잡음의 40배가 넘는다. 45분 실험으로도 a 가 나오기는 한다 — 다만
신뢰구간이 넓고, 긴 자료가 쌓이면 좁아진다.

PRBS 는 언제 쓰나
-----------------
서너 시간을 낼 수 있을 때만 쓴다. 의사난수 이진열은 입력이 느린 표류와
상관이 없어져 표류를 자동으로 걸러 내는데, 그 이점은 수열이 충분히 길어야
나온다. 짧은 창에서는 오히려 구조화된 스텝(compact_calibration_plan)이 낫다.
비트를 짧게 줄여 억지로 끼워 넣으면 계가 못 따라와 입력이 평균으로만 보인다.

비트 길이는 PWM 주기(30초)의 정수배라야 한다. 아니면 비트 경계마다
반 토막 난 PWM 주기가 생겨 입력이 기록과 어긋난다.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

# 최대길이수열을 만드는 되먹임 위치. x^5+x^3+1 처럼 원시다항식에서 온다.
# 여기 없는 차수를 쓰려면 원시다항식을 확인하고 추가해야 한다 — 아무
# 위치나 넣으면 주기가 2^n-1 보다 짧아져 가진이 편향된다.
_MLS_TAPS = {
    4: (4, 3),
    5: (5, 3),
    6: (6, 5),
    7: (7, 6),
    8: (8, 6, 5, 4),
    9: (9, 5),
    10: (10, 7),
}

# 히터 PWM 주기(초). firmware/ir_01 의 HEATER_PWM_PERIOD_MS 와 맞춰야 한다.
PWM_PERIOD_SEC = 30.0

# 기본 가진 폭.
#
# 상한을 100% 로 두지 않는 이유: 10W 를 계속 넣으면 정상상태가 외기보다
# 14'C 높아진다(UA=0.7W/K 추정). 실내 26'C 면 40'C 라 안전 상한 45'C 에
# 너무 가깝다. 35% 면 상승이 약 5'C 이고 이는 재실 10명 상당이라, 열적으로
# 안전하면서 물리적으로도 말이 되는 지점이다.
#
# UA 가 교정되면 이 값을 다시 계산해야 한다. 교정 전에는 추정에 기댄 값이다.
DEFAULT_LOW_DUTY_PCT = 0
DEFAULT_HIGH_DUTY_PCT = 35
DEFAULT_BIT_SEC = 600.0
DEFAULT_N_BITS = 5


def maximum_length_sequence(n_bits: int, seed: int = 1) -> list[int]:
    """주기 2^n-1 의 최대길이수열을 만든다.

    Fibonacci LFSR. 상태가 전부 0 이면 영원히 0 이 나오므로 막는다.
    """
    if n_bits not in _MLS_TAPS:
        raise ValueError(
            f"차수 {n_bits} 의 되먹임 위치를 모릅니다. "
            f"쓸 수 있는 차수: {sorted(_MLS_TAPS)}"
        )
    taps = _MLS_TAPS[n_bits]
    state = [(seed >> i) & 1 for i in range(n_bits)]
    if not any(state):
        state[0] = 1

    out: list[int] = []
    for _ in range((1 << n_bits) - 1):
        out.append(state[-1])
        feedback = 0
        for tap in taps:
            feedback ^= state[tap - 1]
        state = [feedback] + state[:-1]
    return out


@dataclass(frozen=True)
class ExcitationPlan:
    """(duty, 지속시간) 구간의 나열. 시각만 주면 duty 가 정해진다.

    상태를 들고 있지 않은 것이 중요하다. 게이트웨이가 한밤중에 재시작해도
    시작 시각과 계획만 있으면 같은 duty 가 다시 계산된다. 8시간짜리 실험이
    재시작 한 번에 날아가면 안 된다.
    """

    name: str
    segments: tuple[tuple[int, float], ...]   # (duty_pct, 지속시간(초))
    description: str = ""

    @property
    def total_sec(self) -> float:
        return sum(duration for _, duration in self.segments)

    def duty_at(self, elapsed_sec: float) -> int | None:
        """경과 시간에 해당하는 duty. 계획이 끝났으면 None."""
        if elapsed_sec < 0:
            return None
        cursor = 0.0
        for duty, duration in self.segments:
            cursor += duration
            if elapsed_sec < cursor:
                return duty
        return None

    def to_dict(self) -> dict:
        """DB 에 그대로 넣을 수 있는 형태. 재시작 후 이걸로 되살린다."""
        return {
            "name": self.name,
            "description": self.description,
            "segments": [[duty, duration] for duty, duration in self.segments],
        }

    @classmethod
    def from_dict(cls, data: dict) -> "ExcitationPlan":
        return cls(
            name=data["name"],
            segments=tuple((int(d), float(t)) for d, t in data["segments"]),
            description=data.get("description", ""),
        )

    def summary(self) -> str:
        hours = self.total_sec / 3600.0
        duties = sorted({duty for duty, _ in self.segments})
        return (
            f"{self.name}: 구간 {len(self.segments)}개, "
            f"총 {hours:.1f}시간, duty {duties}"
        )


def _round_to_pwm(seconds: float) -> float:
    """PWM 주기의 정수배로 맞춘다. 최소 한 주기."""
    periods = max(1, round(seconds / PWM_PERIOD_SEC))
    return periods * PWM_PERIOD_SEC


def step_calibration_plan(
    settle_sec: float = 1200.0,
    heat_sec: float = 1200.0,
    decay_sec: float = 2400.0,
    heat_duty_pct: int = 100,
) -> ExcitationPlan:
    """교정용 스텝. C 와 UA 를 처음 한 번 실측으로 못 박는다.

    PRBS 보다 먼저 이걸 돌려야 한다. PRBS 의 duty 상한을 정하려면 UA 를
    알아야 하는데, 교정 전에는 추정값(0.7W/K)에 기대고 있기 때문이다.

      1) duty 0    -> 표류 d 와 잡음 바닥 확인
      2) duty 100  -> 초기 기울기에서 C = P / (dT/dt)
      3) duty 0    -> 감쇠에서 tau, 그리고 UA = C / tau

    duty 100 을 20분만 거는 이유: 10W 를 계속 넣으면 정상상태가 외기 +14'C
    다. 20분이면 상승이 3.5'C 라 안전 상한(45'C)에 여유가 크고, 초기
    기울기를 재기에는 충분하다.
    """
    return ExcitationPlan(
        name="step_calibration",
        segments=(
            (0, _round_to_pwm(settle_sec)),
            (heat_duty_pct, _round_to_pwm(heat_sec)),
            (0, _round_to_pwm(decay_sec)),
        ),
        description="C 와 UA 교정용 스텝 응답",
    )


def prbs_plan(
    bit_sec: float = DEFAULT_BIT_SEC,
    n_bits: int = DEFAULT_N_BITS,
    low_duty_pct: int = DEFAULT_LOW_DUTY_PCT,
    high_duty_pct: int = DEFAULT_HIGH_DUTY_PCT,
    seed: int = 1,
    settle_sec: float = 600.0,
) -> ExcitationPlan:
    """PRBS 가진. 밤새 돌려 a, b, c, d 를 한꺼번에 식별한다.

    앞에 정지 구간을 두는 이유는, 시작 시점의 온도가 이전 조작의 과도상태
    한복판이면 첫 몇 비트가 오염되기 때문이다.
    """
    if not 0 <= low_duty_pct <= 100 or not 0 <= high_duty_pct <= 100:
        raise ValueError("duty 는 0~100 이어야 합니다")
    if low_duty_pct >= high_duty_pct:
        raise ValueError("low_duty_pct 는 high_duty_pct 보다 작아야 합니다")

    bit_sec = _round_to_pwm(bit_sec)
    bits = maximum_length_sequence(n_bits, seed)
    segments: list[tuple[int, float]] = [(low_duty_pct, _round_to_pwm(settle_sec))]
    segments.extend(
        (high_duty_pct if bit else low_duty_pct, bit_sec) for bit in bits
    )
    return ExcitationPlan(
        name="prbs",
        segments=tuple(segments),
        description=(
            f"PRBS n={n_bits}(N={len(bits)}), 비트 {bit_sec/60:.0f}분, "
            f"duty {low_duty_pct}/{high_duty_pct}%"
        ),
    )


def check_prbs_design(
    bit_sec: float, n_bits: int, tau_min: float,
) -> list[str]:
    """가진 설계가 시정수에 비해 말이 되는지 본다. 경고 목록을 돌려준다.

    실험을 돌리기 전에 부른다. 8시간 뒤에야 "비트가 너무 짧았다" 를 아는
    것보다 지금 아는 편이 낫다.
    """
    warnings: list[str] = []
    tau_sec = tau_min * 60.0
    n_seq = (1 << n_bits) - 1
    total_sec = bit_sec * n_seq

    if bit_sec < tau_sec / 10:
        warnings.append(
            f"비트 길이 {bit_sec/60:.0f}분이 시정수({tau_min:.0f}분)의 1/10 보다 "
            f"짧습니다 — 계가 못 따라와 입력이 평균으로만 보입니다"
        )
    if bit_sec > tau_sec / 2:
        warnings.append(
            f"비트 길이 {bit_sec/60:.0f}분이 시정수의 1/2 를 넘습니다 — "
            f"매 비트가 정상상태에 닿아 동특성 정보가 줄어듭니다"
        )
    if total_sec < 3 * tau_sec:
        warnings.append(
            f"수열 전체가 {total_sec/3600:.1f}시간으로 시정수의 "
            f"{total_sec/tau_sec:.1f}배뿐입니다 — 3배 이상을 권합니다"
        )
    if not math.isclose(bit_sec % PWM_PERIOD_SEC, 0.0, abs_tol=1e-6):
        warnings.append(
            f"비트 길이가 PWM 주기({PWM_PERIOD_SEC:.0f}초)의 정수배가 "
            f"아닙니다 — 비트 경계마다 반 토막 난 주기가 생깁니다"
        )
    return warnings


def compact_calibration_plan(
    settle_sec: float = 600.0,
    heat_sec: float = 900.0,
    decay_sec: float = 1200.0,
    heat_duty_pct: int = 100,
) -> ExcitationPlan:
    """45분짜리 교정. 사람이 붙어 있을 수 있는 시간에 맞춘 기본 실험.

    긴 실험을 낼 수 없을 때 쓴다. c(히터 감도)와 d(표류)를 확실히 뽑고,
    a(1/시정수)는 넓은 신뢰구간으로나마 얻는다. a 는 이후 평소 운전
    기록의 무가진 구간이 쌓이면서 저절로 좁아진다.

      1) duty 0   10분  -> 표류 d 와 잡음 바닥
      2) duty 100 15분  -> 초기 기울기 -> C = P / (dT/dt), 상승 약 2.7'C
      3) duty 0   20분  -> 감쇠 -> a. 0.68'C 꺾이며 잡음의 40배다.

    실험 중에는 config.app.control_mode 를 shadow 로 두어 냉방이 끼어들지
    않게 한다. 냉각률 b 는 이 실험이 아니라 평소 rule 운전 기록에서 뽑는다 —
    거기엔 냉방 on/off 가 이미 충분히 들어 있다.

    duty 100 을 15분만 거는 이유: 10W 를 계속 넣으면 정상상태가 외기보다
    14'C 높다(UA=0.7W/K 추정). 15분이면 상승이 2.7'C 라 안전 상한(45'C)에
    여유가 크고, 초기 기울기를 재기에는 남는다.
    """
    return ExcitationPlan(
        name="compact_calibration",
        segments=(
            (0, _round_to_pwm(settle_sec)),
            (heat_duty_pct, _round_to_pwm(heat_sec)),
            (0, _round_to_pwm(decay_sec)),
        ),
        description="45분 교정 — c 와 d 확정, a 는 넓은 구간으로",
    )


def pilot_20min_plan() -> ExcitationPlan:
    """PINN/RC 파이프라인 점검용 20분 파일럿 가진.

    이 길이로 시정수나 PINN을 확정하지 않는다. 히터 상승·자연감쇠·문 개방·
    펠티어 냉각의 타임스탬프와 센서 응답이 정렬되는지 확인하는 run이다.
    문은 11~12분에 사람이 열고, 펠티어는 15~18분에 운영자가 별도 명령한다.
    """
    return ExcitationPlan(
        name="pilot_20min",
        segments=(
            (0, _round_to_pwm(180.0)),    # 0~3분: 폐문 안정화
            (35, _round_to_pwm(300.0)),   # 3~8분: 3.5W 상당 열 step
            (0, _round_to_pwm(720.0)),    # 8~20분: 감쇠/문/냉각 구간
        ),
        description=(
            "20분 파일럿 — 0~3 안정화, 3~8 히터35%, 8~11 감쇠, "
            "11~12 문 열림, 12~15 회복, 15~18 펠티어ON, 18~20 OFF"
        ),
    )
