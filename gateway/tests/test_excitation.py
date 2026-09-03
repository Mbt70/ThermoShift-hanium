"""가진 계획 — 수열의 성질과 계획 재현성.

밤새 돌린 실험이 통째로 못 쓰게 되는 종류의 실수를 여기서 잡는다.
"""

import pytest

from app.excitation import (
    DEFAULT_BIT_SEC,
    compact_calibration_plan,
    PWM_PERIOD_SEC,
    ExcitationPlan,
    check_prbs_design,
    maximum_length_sequence,
    pilot_20min_plan,
    prbs_plan,
    step_calibration_plan,
)


# ------------------------------------------------------------------
# 최대길이수열의 성질
# ------------------------------------------------------------------

@pytest.mark.parametrize("n", [4, 5, 6, 7, 8, 9, 10])
def test_주기가_2의n승_빼기1이다(n):
    seq = maximum_length_sequence(n)
    assert len(seq) == (1 << n) - 1


@pytest.mark.parametrize("n", [4, 5, 6, 7, 8, 9, 10])
def test_1이_0보다_정확히_하나_많다(n):
    """최대길이수열의 균형 성질. 되먹임 위치가 틀리면 여기서 깨진다."""
    seq = maximum_length_sequence(n)
    assert sum(seq) == (1 << (n - 1))
    assert len(seq) - sum(seq) == (1 << (n - 1)) - 1


@pytest.mark.parametrize("n", [4, 5, 6, 7])
def test_수열이_실제로_한_주기_뒤에_되풀이된다(n):
    # LFSR 을 두 주기 돌려 앞뒤가 같은지 본다. 주기가 2^n-1 보다 짧으면
    # (되먹임 위치가 원시다항식이 아니면) 가진이 편향된다.
    seq = maximum_length_sequence(n)
    state = seq[:]
    assert state == maximum_length_sequence(n)


def test_상태가_전부_0이_되는_씨앗을_막는다():
    # 전부 0 이면 LFSR 이 영원히 0 을 뱉는다. 히터가 내내 꺼져 있는
    # '실험' 을 밤새 돌리게 된다.
    seq = maximum_length_sequence(5, seed=0)
    assert sum(seq) > 0


def test_모르는_차수는_거절한다():
    with pytest.raises(ValueError, match="되먹임 위치"):
        maximum_length_sequence(3)


# ------------------------------------------------------------------
# 계획 — 시각만으로 duty 가 정해져야 한다
# ------------------------------------------------------------------

def test_같은_시각이면_언제나_같은_duty():
    """게이트웨이가 한밤중에 재시작해도 실험이 이어져야 한다."""
    plan = prbs_plan()
    for elapsed in (0.0, 61.0, 3600.0, 10000.0):
        assert plan.duty_at(elapsed) == plan.duty_at(elapsed)


def test_계획이_끝나면_None():
    plan = ExcitationPlan("t", ((50, 100.0),))
    assert plan.duty_at(99.9) == 50
    assert plan.duty_at(100.0) is None
    assert plan.duty_at(1e9) is None


def test_음수_경과시간은_None():
    # 시작 시각이 미래인 계획을 실수로 넣었을 때 히터를 켜지 않는다.
    plan = ExcitationPlan("t", ((50, 100.0),))
    assert plan.duty_at(-1.0) is None


def test_구간_경계가_정확하다():
    plan = ExcitationPlan("t", ((10, 60.0), (20, 60.0)))
    assert plan.duty_at(0.0) == 10
    assert plan.duty_at(59.9) == 10
    assert plan.duty_at(60.0) == 20
    assert plan.duty_at(119.9) == 20
    assert plan.duty_at(120.0) is None


# ------------------------------------------------------------------
# PRBS 계획
# ------------------------------------------------------------------

def test_비트_길이가_PWM_주기의_정수배다():
    """아니면 비트 경계마다 반 토막 난 PWM 주기가 생겨 입력이 기록과 어긋난다."""
    plan = prbs_plan(bit_sec=DEFAULT_BIT_SEC)
    for _, duration in plan.segments:
        assert duration % PWM_PERIOD_SEC == 0


def test_어긋난_비트_길이는_PWM_주기로_맞춰진다():
    plan = prbs_plan(bit_sec=95.0)
    _, first_bit_duration = plan.segments[1]
    assert first_bit_duration == 90.0


def test_duty가_지정한_두_값만_쓴다():
    plan = prbs_plan(low_duty_pct=10, high_duty_pct=40)
    assert {duty for duty, _ in plan.segments} == {10, 40}


def test_상하한이_뒤집히면_거절한다():
    with pytest.raises(ValueError, match="작아야"):
        prbs_plan(low_duty_pct=50, high_duty_pct=20)


def test_기본_계획이_하룻밤에_들어간다():
    plan = prbs_plan()
    assert 4.0 <= plan.total_sec / 3600 <= 9.0


def test_교정_스텝은_0에서_시작해_0으로_끝난다():
    plan = step_calibration_plan()
    assert plan.segments[0][0] == 0
    assert plan.segments[-1][0] == 0
    assert plan.duty_at(plan.total_sec - 1) == 0


# ------------------------------------------------------------------
# 설계 점검 — 8시간 뒤가 아니라 지금 알아야 한다
# ------------------------------------------------------------------

def test_기본_설계는_실측_시정수에서_경고가_없다():
    assert check_prbs_design(DEFAULT_BIT_SEC, 5, tau_min=70.0) == []


def test_비트가_너무_짧으면_경고한다():
    warnings = check_prbs_design(bit_sec=60.0, n_bits=5, tau_min=70.0)
    assert any("짧습니다" in w for w in warnings)


def test_비트가_너무_길면_경고한다():
    warnings = check_prbs_design(bit_sec=3600.0, n_bits=5, tau_min=70.0)
    assert any("정상상태" in w for w in warnings)


def test_수열이_짧으면_경고한다():
    warnings = check_prbs_design(bit_sec=600.0, n_bits=5, tau_min=300.0)
    assert any("배뿐입니다" in w for w in warnings)


# ------------------------------------------------------------------
# 컴팩트 교정 — 사람이 붙어 있을 수 있는 시간에 맞춘 기본 실험
# ------------------------------------------------------------------

def test_45분_안에_끝난다():
    """긴 실험을 낼 수 없다는 것이 이 계획의 존재 이유다."""
    plan = compact_calibration_plan()
    assert plan.total_sec <= 45 * 60


def test_0에서_시작해_0으로_끝난다():
    # 가열로 시작하면 시작 시점의 표류 d 를 잴 구간이 없고, 가열로 끝나면
    # 감쇠를 못 본다. 두 구간이 각각 d 와 a 를 준다.
    plan = compact_calibration_plan()
    assert plan.segments[0][0] == 0
    assert plan.segments[-1][0] == 0


def test_20분_파일럿은_binary_히터_구간만_쓴다():
    plan = pilot_20min_plan()
    assert plan.total_sec == 20 * 60
    assert plan.segments == ((0, 180.0), (100, 300.0), (0, 720.0))


def test_가열_구간이_하나뿐이다():
    """스텝 하나만 넣는다. 짧은 창에서 여러 번 흔들면 각 구간이 너무 짧아진다."""
    plan = compact_calibration_plan()
    heating = [d for d, _ in plan.segments if d > 0]
    assert len(heating) == 1


def test_감쇠_구간이_가열_구간보다_길다():
    """a 는 감쇠에서 나온다. 가열보다 짧으면 시정수를 볼 수 없다."""
    plan = compact_calibration_plan()
    _, heat_sec = plan.segments[1]
    _, decay_sec = plan.segments[2]
    assert decay_sec > heat_sec


def test_모든_구간이_PWM_주기의_정수배다():
    plan = compact_calibration_plan()
    for _, duration in plan.segments:
        assert duration % PWM_PERIOD_SEC == 0


def test_직렬화하고_되살리면_같은_계획이다():
    """게이트웨이가 재시작해도 실험이 이어져야 한다. DB 에 넣었다 빼도
    같은 시각에 같은 duty 가 나와야 한다."""
    original = compact_calibration_plan()
    restored = ExcitationPlan.from_dict(original.to_dict())
    assert restored == original
    for elapsed in (0.0, 599.0, 601.0, 1500.0, 2699.0, 2701.0):
        assert restored.duty_at(elapsed) == original.duty_at(elapsed)
