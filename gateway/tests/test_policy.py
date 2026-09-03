"""제어 정책 시험.

정책이 순수 함수라 MQTT·DB 없이 상황을 그대로 만들어 볼 수 있다. 시험이
곧 "이 시스템이 어떤 상황에서 무엇을 하는가" 의 명세다.
"""

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from app.policy import (PolicyConfig, PolicyInput, ScheduleWindow, decide)
from ml.thermal_model import ThermalModel

NOW = datetime(2026, 8, 30, 14, 0, tzinfo=timezone.utc)
CFG = PolicyConfig()


def history(minutes: int, value: float, now=NOW, step_sec=30):
    """now 까지 minutes 분 동안 value 를 유지한 온도 이력."""
    n = int(minutes * 60 / step_sec)
    return [(now - timedelta(seconds=step_sec * i), value)
            for i in range(n, -1, -1)]


def base(**kw):
    args = dict(now=NOW, temperature_c=24.0, co2_ppm=700.0,
                temp_history=history(10, 24.0), occupancy_state="OCCUPIED",
                p_occupied=0.9, control_mode="rule")
    args.update(kw)
    return PolicyInput(**args)


# ---------------------------------------------------------------- 안전
def test_센서가_끊기면_현_상태를_유지한다():
    d = decide(base(env_fresh=False, cooling_on=True,
                    current_action="COOL_24_AUTO"), CFG)
    assert d.execute is False
    assert d.blocked_by == "ENV_STALE"
    assert d.action == "COOL_24_AUTO"


def test_수동_잠금_중에는_자동_명령을_내지_않는다():
    d = decide(base(locked_out=True, temperature_c=29.0,
                    temp_history=history(10, 29.0)), CFG)
    assert d.execute is False
    assert d.blocked_by == "MANUAL_LOCKOUT"


# ---------------------------------------------------------------- CO2
def test_CO2가_위험_기준을_넘으면_환기_판단이_된다():
    d = decide(base(co2_ppm=1600.0), CFG)
    assert d.decision_type == "ventilate"
    assert d.execute is False


def test_CO2_환기_판단은_냉방_상태를_바꾸지_않는다():
    # 환기 장치가 없다. 임의로 냉방을 끄면 더운 방에 사람을 남기게 된다.
    d = decide(base(co2_ppm=1600.0, cooling_on=True,
                    current_action="COOL_24_AUTO"), CFG)
    assert d.action == "COOL_24_AUTO"


def test_CO2가_경고_수준이면_근거에만_남고_판단은_계속된다():
    d = decide(base(co2_ppm=1100.0, temperature_c=26.0,
                    temp_history=history(10, 26.0)), CFG)
    assert d.decision_type == "maintain"
    assert any("환기 권장" in r for r in d.reasons)


# ---------------------------------------------------------------- 재실
def test_공실이_확인되면_끈다():
    d = decide(base(occupancy_state="EMPTY", p_occupied=0.02, cooling_on=True,
                    current_action="COOL_24_AUTO", temperature_c=26.0), CFG)
    assert d.decision_type == "off"
    assert d.action == "POWER_OFF"
    assert d.execute is True


def test_전이_상태에서는_현_상태를_유지한다():
    d = decide(base(occupancy_state="TRANSITION", temperature_c=29.0,
                    temp_history=history(10, 29.0)), CFG)
    assert d.execute is False
    assert d.blocked_by == "OCCUPANCY_TRANSITION"


# ---------------------------------------------------------------- 온도
def test_더운_상태가_지속되면_냉방을_켠다():
    d = decide(base(temperature_c=26.5, temp_history=history(10, 26.5)), CFG)
    assert d.decision_type == "maintain"
    assert d.action == "COOL_24_AUTO"
    assert d.execute is True


def test_잠깐_더운_것만으로는_켜지_않는다():
    # 3분 지속 조건을 못 채우면 판단이 바뀌지 않아야 한다.
    d = decide(base(temperature_c=26.5, temp_history=history(1, 26.5)), CFG)
    assert d.decision_type != "maintain"
    assert d.blocked_by == "AWAITING_SUSTAINED_HIGH"


def test_지속조건_미충족을_쾌적범위_안이라고_적지_않는다():
    """근거 문구가 사실과 달라선 안 된다.

    실제로 27℃ 인 방의 제어 로그에 "쾌적 범위 안" 이 남은 적이 있다.
    게이트웨이를 막 재시작해 이력이 짧았던 것뿐인데, 로그만 보면 방이
    쾌적하다는 뜻이 되어 버린다.
    """
    d = decide(base(temperature_c=27.0, temp_history=history(1, 27.0)), CFG)
    assert not any("쾌적 범위 안" in r for r in d.reasons)
    assert any("지속" in r for r in d.reasons)


def test_과냉되면_끈다():
    d = decide(base(temperature_c=22.5, temp_history=history(10, 22.5),
                    cooling_on=True, current_action="COOL_24_AUTO",
                    last_on_at=NOW - timedelta(minutes=30)), CFG)
    assert d.decision_type == "off"
    assert d.execute is True


def test_쾌적_범위_안에서_냉방_중이면_설정을_완화한다():
    d = decide(base(temperature_c=24.0, temp_history=history(10, 24.0),
                    cooling_on=True, current_action="COOL_24_AUTO",
                    last_on_at=NOW - timedelta(minutes=30)), CFG)
    assert d.decision_type == "setback"
    assert d.target_temp_c == pytest.approx(25.5)
    assert d.action == "COOL_26_AUTO"   # 25.5 반올림


def test_쾌적_범위_안이고_이미_꺼져_있으면_아무것도_하지_않는다():
    d = decide(base(temperature_c=24.0, temp_history=history(10, 24.0)), CFG)
    assert d.decision_type == "off"
    assert d.execute is False


# ---------------------------------------------------------------- 기기 보호
def test_정지_직후에는_다시_켜지_않는다():
    d = decide(base(temperature_c=26.5, temp_history=history(10, 26.5),
                    last_off_at=NOW - timedelta(seconds=60)), CFG)
    assert d.decision_type == "maintain"      # 판단은 남는다
    assert d.execute is False                 # 송신만 막힌다
    assert d.blocked_by == "MIN_OFF_TIME"


def test_가동_직후에는_끄지_않는다():
    d = decide(base(occupancy_state="EMPTY", cooling_on=True,
                    current_action="COOL_24_AUTO",
                    last_on_at=NOW - timedelta(seconds=60)), CFG)
    assert d.execute is False
    assert d.blocked_by == "MIN_ON_TIME"


def test_명령_간격_제한이_걸린다():
    d = decide(base(temperature_c=26.5, temp_history=history(10, 26.5),
                    last_command_at=NOW - timedelta(seconds=30)), CFG)
    assert d.execute is False
    assert d.blocked_by == "RATE_LIMIT"


def test_관측_모드는_판단만_하고_송신하지_않는다():
    d = decide(base(temperature_c=26.5, temp_history=history(10, 26.5),
                    control_mode="monitoring"), CFG)
    assert d.decision_type == "maintain"
    assert d.execute is False
    assert d.blocked_by == "MONITORING_MODE"


# ---------------------------------------------------------------- 예냉
def test_예약_직전에_더우면_미리_식힌다():
    sched = ScheduleWindow(NOW + timedelta(minutes=30),
                           NOW + timedelta(minutes=120), 24.0)
    d = decide(base(temperature_c=26.0, occupancy_state="EMPTY",
                    schedule=sched, thermal=ThermalModel()), CFG)
    assert d.decision_type == "precool"
    assert d.action == "COOL_24_AUTO"
    assert d.execute is True


def test_예약이_멀면_아직_켜지_않는다():
    sched = ScheduleWindow(NOW + timedelta(minutes=300),
                           NOW + timedelta(minutes=360), 24.0)
    d = decide(base(temperature_c=26.0, occupancy_state="EMPTY",
                    schedule=sched, thermal=ThermalModel()), CFG)
    assert d.decision_type == "off"


def test_이미_시원하면_예냉하지_않는다():
    sched = ScheduleWindow(NOW + timedelta(minutes=10),
                           NOW + timedelta(minutes=60), 24.0)
    d = decide(base(temperature_c=23.0, occupancy_state="EMPTY",
                    schedule=sched, thermal=ThermalModel()), CFG)
    assert d.decision_type != "precool"


def test_열모델이_없으면_예냉하지_않는다():
    # 리드타임을 모르는 채로 예냉하면 몇 시간씩 헛돌 수 있다.
    sched = ScheduleWindow(NOW + timedelta(minutes=30),
                           NOW + timedelta(minutes=120), 24.0)
    d = decide(base(temperature_c=26.0, occupancy_state="EMPTY",
                    schedule=sched, thermal=None), CFG)
    assert d.decision_type != "precool"


def test_예냉_리드타임이_상한을_넘으면_상한에서_시작한다():
    # 31℃ 는 계산상 112분이 필요하지만 상한이 90분이다. 그보다 일찍 켜지
    # 않고, 상한 안(85분 전)에 들어오면 그때 시작한다.
    thermal = ThermalModel()
    assert thermal.lead_time_minutes(31.0, 24.0) > CFG.precool_max_lead_min

    early = decide(base(temperature_c=31.0, occupancy_state="EMPTY",
                        schedule=ScheduleWindow(NOW + timedelta(minutes=100),
                                                NOW + timedelta(minutes=200), 24.0),
                        thermal=thermal), CFG)
    assert early.decision_type != "precool"      # 상한보다 이르면 켜지 않는다

    d = decide(base(temperature_c=31.0, occupancy_state="EMPTY",
                    schedule=ScheduleWindow(NOW + timedelta(minutes=85),
                                            NOW + timedelta(minutes=200), 24.0),
                    thermal=thermal), CFG)
    assert d.decision_type == "precool"


def test_예약_진행_중에는_예약_목표_온도를_쓴다():
    sched = ScheduleWindow(NOW - timedelta(minutes=10),
                           NOW + timedelta(minutes=60), 22.0)
    d = decide(base(temperature_c=25.0, temp_history=history(10, 25.0),
                    schedule=sched), CFG)
    assert d.decision_type == "maintain"
    assert d.action == "COOL_22_AUTO"


def test_mpc_모드에서_쾌적_상태이면_setback_최적화한다():
    d = decide(base(temperature_c=24.5, humidity_pct=45.0, occupancy_state="OCCUPIED",
                    p_occupied=0.95, control_mode="mpc"), CFG)
    assert d.decision_type == "setback"
    assert any("MPC 최적화" in r for r in d.reasons)


def test_mpc_모드에서_덥고_재실중이면_maintain_최적화한다():
    d = decide(base(temperature_c=27.5, humidity_pct=75.0, occupancy_state="OCCUPIED",
                    p_occupied=0.95, control_mode="mpc"), CFG)
    assert d.decision_type == "maintain"
    assert any("MPC 최적화" in r for r in d.reasons)

