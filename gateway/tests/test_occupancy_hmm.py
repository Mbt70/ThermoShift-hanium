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

def test_pir_detection_triggers_occupied(hmm):
    features = {
        "pir_recent": True,
        "pir_age_sec": 10,
        "door_recent": False,
        "door_age_sec": 300,
        "co2_slope_5m": 1.0,
        "co2_delta_baseline": 50,
        "occ_fresh": True
    }
    state, probs, reasons = hmm.update(features)
    assert state == "OCCUPIED"
    assert probs[2] >= 0.90

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
        "pir_age_sec": 1000, # > 15m
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
