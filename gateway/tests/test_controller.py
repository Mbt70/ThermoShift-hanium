import pytest
from datetime import datetime, timezone, timedelta
from app.controller import HVACController
from app.config import get_config

class MockIRAdapter:
    def __init__(self):
        self.locked_out = False
        self.sent_commands = []
    
    def is_locked_out(self):
        return self.locked_out
        
    def send_command(self, cmd):
        self.sent_commands.append(cmd)

class MockStorage:
    def insert_control_decision(self, *args, **kwargs):
        pass
    def insert_system_event(self, *args, **kwargs):
        pass

@pytest.fixture
def controller(monkeypatch):
    monkeypatch.setattr("app.controller.get_storage", lambda: MockStorage())
    
    class MockDataQuality:
        class FakeEnv:
            temperature_c = 27.0
            co2_ppm = 800
        latest_env = {"test": FakeEnv()}
    monkeypatch.setattr("app.controller.get_data_quality", lambda: MockDataQuality())

    class MockFeatureEngine:
        @property
        def temp_history(self):
            now = datetime.now(timezone.utc)
            return [
                (now - timedelta(minutes=4), 27.0),
                (now - timedelta(minutes=3), 27.0),
                (now - timedelta(minutes=2), 27.0),
                (now - timedelta(minutes=1), 27.0),
                (now, 27.0)
            ]
    monkeypatch.setattr("app.controller.get_feature_engine", lambda: MockFeatureEngine())

    ir = MockIRAdapter()
    c = HVACController(ir)
    c.config.app.control_mode = "shadow"
    return c

def test_shadow_mode_does_not_transmit(controller):
    features = {"env_fresh": True}
    p_occ = {"empty": 0.0, "transition": 0.0, "occupied": 1.0}
    
    decision = controller.decide(features, "OCCUPIED", p_occ)
    
    assert decision["proposed_action"] == "COOL_25_AUTO"
    assert decision["executed"] is False
    assert len(controller.ir.sent_commands) == 0
    assert "SHADOW_MODE_NO_TRANSMIT" in decision["reason_codes"]

def test_failsafe_on_stale_env(controller):
    features = {"env_fresh": False}
    decision = controller.decide(features, "OCCUPIED", {"empty":0, "transition":0, "occupied":1})
    assert "ENV_STALE" in decision["reason_codes"]
    assert decision["proposed_action"] == "POWER_OFF"

def test_manual_lockout_prevents_action(controller):
    controller.ir.locked_out = True
    features = {"env_fresh": True}
    decision = controller.decide(features, "OCCUPIED", {"empty":0, "transition":0, "occupied":1})
    assert "MANUAL_LOCKOUT" in decision["reason_codes"]
    # Still proposes, but wouldn't execute even in active mode
    assert decision["executed"] is False
