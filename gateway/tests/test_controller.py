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
    def resolve_room_id(self):
        # None -> controller skips the schedule(precool) lookup entirely,
        # which is what these tests want (they're not exercising precool).
        return None

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
    # gateway.app.policy (adopted as the real decision engine) flags this
    # via blocked_by rather than an old-controller-style reason code string.
    assert decision["blocked_by"] == "MONITORING_MODE"

def test_failsafe_on_stale_env(controller):
    features = {"env_fresh": False}
    decision = controller.decide(features, "OCCUPIED", {"empty":0, "transition":0, "occupied":1})
    assert decision["blocked_by"] == "ENV_STALE"
    assert decision["proposed_action"] == "POWER_OFF"

def test_manual_lockout_prevents_action(controller):
    controller.ir.locked_out = True
    features = {"env_fresh": True}
    decision = controller.decide(features, "OCCUPIED", {"empty":0, "transition":0, "occupied":1})
    assert decision["blocked_by"] == "MANUAL_LOCKOUT"
    # Still proposes, but wouldn't execute even in active mode
    assert decision["executed"] is False


class MockStorageWithSchedule(MockStorage):
    """예약이 하나 있는 경우 - 선냉방(precool) 경로를 태우기 위한 목."""

    def __init__(self, minutes_until_start: float, target_temp: float):
        now = datetime.now(timezone.utc)
        start = now + timedelta(minutes=minutes_until_start)
        end = start + timedelta(hours=1)
        self.schedule_row = {
            "schedule_id": 1,
            "start_time": start.time(),
            "end_time": end.time(),
            "target_temp": target_temp,
            "precooling_min": 0,
        }

    def resolve_room_id(self):
        return 1

    def get_upcoming_schedule(self, room_id, now):
        return self.schedule_row


def _make_controller(monkeypatch, storage, temperature_c=27.0, control_mode="active"):
    monkeypatch.setattr("app.controller.get_storage", lambda: storage)

    class MockDataQuality:
        class FakeEnv:
            pass
        FakeEnv.temperature_c = temperature_c
        FakeEnv.co2_ppm = 800
        latest_env = {"test": FakeEnv()}
    monkeypatch.setattr("app.controller.get_data_quality", lambda: MockDataQuality())

    class MockFeatureEngine:
        temp_history = []
    monkeypatch.setattr("app.controller.get_feature_engine", lambda: MockFeatureEngine())

    ir = MockIRAdapter()
    c = HVACController(ir)
    c.config.app.control_mode = control_mode
    return c


def test_precool_fires_when_lead_time_covers_the_gap(monkeypatch):
    """열모델(미교정 기본값) 기준 27->24도는 약 57분 걸린다. 예약이 40분
    뒤에 시작하면 지금 미리 켜야 한다 - 이게 '예측 제어'의 최소 버전이다.
    """
    storage = MockStorageWithSchedule(minutes_until_start=40, target_temp=24.0)
    controller = _make_controller(monkeypatch, storage, temperature_c=27.0)

    decision = controller.decide({"env_fresh": True}, "EMPTY", {"empty": 1, "transition": 0, "occupied": 0})

    assert decision["decision_type"] == "precool"
    assert decision["proposed_action"] == "COOL_24_AUTO"
    assert decision["executed"] is True
    assert controller.ir.sent_commands == ["COOL_24_AUTO"]


def test_precool_waits_when_schedule_is_still_far_off(monkeypatch):
    """같은 상황인데 예약이 훨씬 더 뒤(120분 뒤)면, 아직 켤 때가 아니다."""
    storage = MockStorageWithSchedule(minutes_until_start=120, target_temp=24.0)
    controller = _make_controller(monkeypatch, storage, temperature_c=27.0)

    decision = controller.decide({"env_fresh": True}, "EMPTY", {"empty": 1, "transition": 0, "occupied": 0})

    assert decision["decision_type"] != "precool"
    assert decision["executed"] is False
