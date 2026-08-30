"""합성 재실자 — 환산과 안전 차단.

무인으로 밤새 가열하는 장치라, 여기서 놓친 것은 현장에서 되돌릴 수 없다.
안전 차단을 순수 함수로 뽑아 둔 이유가 그것이다.
"""

import pytest

from app.heater import (
    HeaterController,
    SyntheticOccupant,
    MAX_BOX_TEMP_C,
    MAX_TEMP_STALENESS_SEC,
    PERSON_DELTA_T_K,
    safe_duty,
)


@pytest.fixture
def scale():
    # 교정 전 추정값과 같은 값을 명시적으로 쓴다. 기본값이 바뀌어도
    # 이 시험이 검증하는 '환산 규칙' 은 그대로여야 한다.
    return SyntheticOccupant(box_ua_w_per_k=0.7, pad_power_w=10.0)


# ------------------------------------------------------------------
# 스케일링 계약
# ------------------------------------------------------------------

def test_1인_상당은_기준공간의_온도상승으로_정의된다(scale):
    assert scale.watts_per_person == pytest.approx(PERSON_DELTA_T_K * 0.7)


def test_인원과_duty_환산이_서로_역이다(scale):
    for n in (5, 10, 20):
        duty = scale.duty_for_occupants(n)
        assert scale.occupants_for_duty(duty) == pytest.approx(n, abs=0.2)


def test_음수_인원은_duty_0(scale):
    assert scale.duty_for_occupants(-3) == 0
    assert scale.duty_for_occupants(0) == 0


def test_정원을_넘겨도_duty는_100을_넘지_않는다(scale):
    assert scale.duty_for_occupants(1000) == 100


def test_교정_전에는_calibrated가_False다(scale):
    # UI·보고서에서 '가정값' 으로 표시해야 하므로 이 플래그가 중요하다.
    assert scale.calibrated is False


# ------------------------------------------------------------------
# 안전 차단
# ------------------------------------------------------------------

def test_온도를_모르면_가열하지_않는다():
    duty, reason = safe_duty(60, temperature_c=None, temp_age_sec=0.0)
    assert duty == 0
    assert reason is not None


def test_측정이_오래되면_가열하지_않는다():
    duty, reason = safe_duty(
        60, temperature_c=25.0, temp_age_sec=MAX_TEMP_STALENESS_SEC + 1,
    )
    assert duty == 0
    assert "초 전" in reason


def test_상한_온도에_닿으면_차단한다():
    duty, reason = safe_duty(60, temperature_c=MAX_BOX_TEMP_C, temp_age_sec=0.0)
    assert duty == 0
    assert reason is not None


def test_상한_아래에서는_그대로_통과한다():
    duty, reason = safe_duty(60, temperature_c=MAX_BOX_TEMP_C - 5, temp_age_sec=0.0)
    assert duty == 60
    assert reason is None


def test_duty_0_요청은_센서가_없어도_사유_없이_통과한다():
    # 끄는 것은 언제나 안전하다. 여기서 경고를 내면 히터를 안 쓰는
    # 설치에서도 로그가 차단 사유로 가득 찬다.
    duty, reason = safe_duty(0, temperature_c=None, temp_age_sec=None)
    assert duty == 0
    assert reason is None


# ------------------------------------------------------------------
# 발행 동작 — 노드 워치독이 여기에 달려 있다
# ------------------------------------------------------------------

class _Spy:
    def __init__(self):
        self.sent = []

    def __call__(self, topic, payload):
        self.sent.append((topic, payload))


def test_값이_그대로여도_매_주기_발행한다(scale):
    # 노드 워치독(120초)이 이 발행을 먹고 산다. 변화가 있을 때만 보내면
    # 게이트웨이가 멀쩡한데도 노드가 히터를 꺼 버린다.
    spy = _Spy()
    heater = HeaterController(spy, "t/heater/cmd", scale=scale)
    heater.request_duty(40)
    for _ in range(3):
        heater.tick(25.0, 0.0)
    assert spy.sent == [("t/heater/cmd", "40")] * 3


def test_차단되면_0을_발행한다(scale):
    spy = _Spy()
    heater = HeaterController(spy, "t/heater/cmd", scale=scale)
    heater.request_duty(80)
    heater.tick(MAX_BOX_TEMP_C + 1, 0.0)
    assert spy.sent[-1] == ("t/heater/cmd", "0")
    assert heater.applied_duty == 0


def test_차단이_풀리면_다시_올라간다(scale):
    spy = _Spy()
    heater = HeaterController(spy, "t/heater/cmd", scale=scale)
    heater.request_duty(80)
    heater.tick(MAX_BOX_TEMP_C + 1, 0.0)
    heater.tick(25.0, 0.0)
    assert heater.applied_duty == 80


def test_적용된_인원_상당을_돌려준다(scale):
    spy = _Spy()
    heater = HeaterController(spy, "t/heater/cmd", scale=scale)
    heater.request_occupants(10)
    heater.tick(25.0, 0.0)
    assert heater.applied_occupants == pytest.approx(10, abs=0.3)
