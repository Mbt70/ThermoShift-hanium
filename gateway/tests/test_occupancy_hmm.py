import pytest
from datetime import datetime, timezone
from app.occupancy_hmm import OccupancyHMM
from app.config import get_config

# Mock storage to avoid db writes during tests
class MockStorage:
    def insert_occupancy_estimate(self, *args, **kwargs):
        pass
    def insert_sensor_reading(self, *args, **kwargs):
        pass
    def insert_control_decision(self, *args, **kwargs):
        pass

@pytest.fixture
def hmm(monkeypatch):
    monkeypatch.setattr("app.occupancy_hmm.get_storage", lambda: MockStorage())
    # Ensure config has defaults
    cfg = get_config()
    return OccupancyHMM()

def test_initial_state(hmm):
    assert hmm.state == "UNKNOWN"

PIR_FEATURES = {
    "pir_recent": True,
    "pir_age_sec": 10,
    "door_recent": False,
    "door_age_sec": 300,
    "co2_slope_5m": 1.0,
    "co2_delta_baseline": 50,
    "occ_fresh": True,
}


def test_pir_detection_raises_probability_immediately(hmm):
    # 확률은 한 번의 관측으로 바로 올라간다.
    before = hmm.probs[2]
    state, probs, reasons = hmm.update(dict(PIR_FEATURES))
    assert probs[2] > before


def test_pir_detection_confirms_occupied_on_second_tick(hmm):
    # 상태 라벨은 두 주기(60초) 연속 확인 뒤에 바뀐다.
    #
    # 예전에는 PIR 이 잡히면 사후확률을 [0.01, 0.04, 0.95] 로 덮어써서 한 번에
    # OCCUPIED 가 됐다. 그 처리를 없앴으므로 오검출 한 번으로는 상태가
    # 뒤집히지 않는다. 냉방은 어차피 온도가 3분 지속돼야 켜지므로 이 60초가
    # 쾌적성을 해치지 않는다.
    assert hmm.update(dict(PIR_FEATURES))[0] == "TRANSITION"
    for _ in range(8):
        state, _, _ = hmm.update(dict(PIR_FEATURES))
        if state == "OCCUPIED":
            break
    assert state == "OCCUPIED"


def test_occupied_decays_to_empty_only_after_confirmation_window(hmm):
    """재실 확정 뒤 조용해지면 어떻게 빠져나오는지.

    PIR 은 사람이 가만히 있으면 잠잠해진다. 그래서 조용해졌다고 바로 공실로
    보면 앉아 있는 사람의 냉방을 끄게 된다. 확률은 곧 내려가되, 상태가
    EMPTY 로 가는 것은 empty_confirmation_sec 을 넘긴 뒤여야 한다.
    """
    for _ in range(3):
        hmm.update(dict(PIR_FEATURES))
    assert hmm.state == "OCCUPIED"

    confirm = hmm.config.control.empty_confirmation_sec
    quiet = lambda age: dict(PIR_FEATURES, pir_recent=False, pir_age_sec=age)

    # 확인 시간 직전까지는 EMPTY 로 가지 않는다.
    age = 30
    while age < confirm:
        state, _, _ = hmm.update(quiet(age))
        assert state != "EMPTY", f"pir_age={age}초에 성급하게 공실 판정"
        age += 30

    # 확인 시간을 넘기면 공실로 확정된다.
    assert hmm.update(quiet(confirm))[0] == "EMPTY"


def test_probability_falls_quickly_once_motion_stops(hmm):
    # 상태 라벨과 달리 확률은 곧바로 반응해야 한다. 대시보드가 이 값을 보여준다.
    for _ in range(3):
        hmm.update(dict(PIR_FEATURES))
    for _ in range(5):
        _, probs, _ = hmm.update(dict(PIR_FEATURES, pir_recent=False, pir_age_sec=150))
    assert probs[2] < 0.10

def test_door_event_without_pir_transitions(hmm):
    features = {
        "pir_recent": False,
        "pir_age_sec": 600,
        "door_recent": True,
        "door_age_sec": 5,
        "co2_slope_5m": 0.0,
        "co2_delta_baseline": 0,
        "occ_fresh": True
    }
    state, probs, reasons = hmm.update(features)
    # With only door and no PIR, it should lean towards TRANSITION
    assert state == "TRANSITION"

def test_empty_confirmation(hmm):
    # Setup state to empty by running an update that fulfills empty conditions
    hmm.probs = [0.90, 0.05, 0.05]
    features = {
        "pir_recent": False,
        "pir_age_sec": 1000,  # > empty_confirmation_sec(900)
        "door_recent": False,
        "door_age_sec": 400, # > 5m
        "co2_slope_5m": -2.0, # not rising
        "co2_delta_baseline": 10,
        "occ_fresh": True
    }
    state, probs, reasons = hmm.update(features)
    assert state == "EMPTY"
    
def test_stale_occ_prevents_empty(hmm):
    hmm.probs = [0.90, 0.05, 0.05]
    features = {
        "pir_recent": False,
        "pir_age_sec": 1000,
        "door_recent": False,
        "door_age_sec": 400,
        "co2_slope_5m": -2.0,
        "co2_delta_baseline": 10,
        "occ_fresh": False # Stale!
    }
    state, probs, reasons = hmm.update(features)
    assert state == "TRANSITION"
