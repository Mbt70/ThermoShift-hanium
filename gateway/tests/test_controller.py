"""컨트롤러 시험 — 오케스트레이션(설정 읽기·송신·기록)을 본다.

판단 자체의 옳고 그름은 test_policy.py 가 표로 만들어 확인한다. 여기서는
그 판단이 실제로 송신으로 이어지는지, 그리고 사용자가 대시보드에서 바꾼
설정이 반영되는지를 본다.
"""

from datetime import datetime, timedelta, timezone

import pytest

from app.controller import HVACController


class MockIRAdapter:
    def __init__(self):
        self.locked_out = False
        self.sent_commands = []
        # 컨트롤러가 히터 발행에 쓴다. 실제 IRAdapter 와 같은 이름이라야
        # 목이 실물 인터페이스에서 어긋나지 않는다.
        self.published = []

    def publish_func(self, topic, payload):
        self.published.append((topic, payload))

    def is_locked_out(self):
        return self.locked_out

    def send_command(self, cmd):
        self.sent_commands.append(cmd)


class MockStorage:
    """대시보드가 정한 공간 설정을 흉내낸다."""

    def __init__(self):
        self.room = {"room_id": 1, "name": "테스트실", "control_mode": "rule",
                     "target_temp": 25.0, "temp_tolerance": 1.0, "co2_limit": 1000}
        self.decisions = []
        self.events = []
        self.heater_logs = []
        self.experiment = None

    def resolve_room_id(self):
        return 1

    def fetch_room_settings(self, room_id):
        return self.room

    def fetch_active_schedule(self, room_id, now):
        return None

    def insert_control_decision(self, *a, **kw):
        self.decisions.append((a, kw))

    def insert_system_event(self, *a, **kw):
        self.events.append((a, kw))

    def fetch_active_experiment(self, room_id):
        return self.experiment

    def stop_experiment(self, run_id, stopped_at):
        self.experiment = None

    def insert_heater_log(self, recorded_at, requested, applied, occupants,
                          blocked_reason=None, run_id=None):
        self.heater_logs.append({
            "requested": requested, "applied": applied,
            "occupants": occupants, "blocked_reason": blocked_reason,
            "run_id": run_id,
        })


@pytest.fixture
def controller(monkeypatch):
    storage = MockStorage()
    monkeypatch.setattr("app.controller.get_storage", lambda: storage)
    # 정책 경로 시험용 모델은 교정 완료로 표시한다. 실제 운전에서는
    # ml/params/thermal.json의 calibrated=true가 없으면 MPC·예냉을 막는다.

    class MockDataQuality:
        class FakeEnv:
            temperature_c = 27.0
            co2_ppm = 800.0
        latest_env = {"test": FakeEnv()}
        last_seen = {"env": datetime.now(timezone.utc)}

    monkeypatch.setattr("app.controller.get_data_quality", lambda: MockDataQuality())

    class MockFeatureEngine:
        @property
        def temp_history(self):
            now = datetime.now(timezone.utc)
            return [(now - timedelta(minutes=m), 27.0) for m in range(10, -1, -1)]

    monkeypatch.setattr("app.controller.get_feature_engine", lambda: MockFeatureEngine())

    class MockHMM:
        last_estimate_id = None

    monkeypatch.setattr("app.controller.get_occupancy_hmm", lambda: MockHMM())

    c = HVACController(MockIRAdapter())
    c.storage = storage
    c.thermal.calibrated = True
    # 무시되는 로컬 config.yaml 값이 테스트 결과를 바꾸면 안 된다.
    c.config.ir.manual_override = None
    c.config.heater.enabled = False
    c.config.heater.manual_duty = None
    return c


FRESH = {"env_fresh": True, "occ_fresh": True}
OCCUPIED = {"empty": 0.0, "transition": 0.0, "occupied": 1.0}
EMPTY = {"empty": 1.0, "transition": 0.0, "occupied": 0.0}


# ---------------------------------------------------------------- 안전 상한
def test_shadow_mode_never_transmits(controller):
    """config.yaml 이 shadow 면 공간 모드가 rule 이어도 송신하지 않는다."""
    controller.config.app.control_mode = "shadow"
    d = controller.decide(FRESH, "OCCUPIED", OCCUPIED)
    assert d["decision_type"] == "maintain"      # 판단은 그대로 남는다
    assert d["executed"] is False
    assert controller.ir.sent_commands == []
    assert d["blocked_by"] == "MONITORING_MODE"


def test_manual_override_cannot_bypass_shadow_mode(controller):
    controller.config.app.control_mode = "shadow"
    controller.config.ir.manual_override = "ON"
    d = controller.decide(FRESH, "OCCUPIED", OCCUPIED)
    assert d["executed"] is False
    assert controller.ir.sent_commands == []


def test_manual_override_cannot_bypass_stale_sensor(controller):
    controller.config.app.control_mode = "active"
    controller.config.ir.manual_override = "ON"
    d = controller.decide(
        {"env_fresh": False, "occ_fresh": True}, "OCCUPIED", OCCUPIED
    )
    assert d["blocked_by"] == "ENV_STALE"
    assert d["executed"] is False
    assert controller.ir.sent_commands == []


def test_manual_override_records_the_command_actually_sent(controller):
    controller.config.app.control_mode = "active"
    controller.config.ir.manual_override = "ON"
    d = controller.decide(FRESH, "OCCUPIED", OCCUPIED)
    assert controller.ir.sent_commands == ["COOL_24_AUTO"]
    assert d["proposed_action"] == "COOL_24_AUTO"
    assert d["decision_type"] == "maintain"
    assert d["target_temp_c"] == 24.0
    assert "MANUAL_OVERRIDE_ON (policy=COOL_25_AUTO)" in d["reason_codes"]
    assert controller.storage.decisions[-1][0][2] == "COOL_24_AUTO"


def test_active_mode_transmits(controller):
    controller.config.app.control_mode = "active"
    d = controller.decide(FRESH, "OCCUPIED", OCCUPIED)
    assert d["executed"] is True
    assert controller.ir.sent_commands == ["COOL_25_AUTO"]


# ---------------------------------------------------- 대시보드 설정 반영
def test_room_target_temp_from_dashboard_is_used(controller):
    """사용자가 화면에서 목표 온도를 바꾸면 다음 판단부터 반영된다."""
    controller.config.app.control_mode = "active"
    controller.storage.room["target_temp"] = 22.0
    d = controller.decide(FRESH, "OCCUPIED", OCCUPIED)
    assert d["proposed_action"] == "COOL_22_AUTO"


def test_monitoring_mode_records_but_does_not_transmit(controller):
    """화면에서 '모니터링' 을 고르면 판단만 남고 냉방은 돌지 않는다."""
    controller.config.app.control_mode = "active"
    controller.storage.room["control_mode"] = "monitoring"
    d = controller.decide(FRESH, "OCCUPIED", OCCUPIED)
    assert d["executed"] is False
    assert controller.ir.sent_commands == []


def test_manual_mode_does_not_run_automatic_control(controller):
    """'수동' 은 자동 제어를 하지 않는다. 큐에 들어온 명령만 실행한다."""
    controller.config.app.control_mode = "active"
    controller.storage.room["control_mode"] = "manual"
    d = controller.decide(FRESH, "OCCUPIED", OCCUPIED)
    assert d["executed"] is False


def test_mpc_mode_runs_optimizer_and_records_provenance(controller):
    """MPC 판단은 실행 여부와 무관하게 근거와 모드를 기록한다."""
    controller.config.app.control_mode = "active"
    controller.storage.room["control_mode"] = "mpc"
    d = controller.decide(FRESH, "OCCUPIED", OCCUPIED)
    assert any("MPC" in r for r in d["reason_codes"])
    assert d["room_mode"] == "mpc"


# ---------------------------------------------------------------- 안전
def test_stale_env_holds_current_state(controller):
    controller.config.app.control_mode = "active"
    d = controller.decide({"env_fresh": False, "occ_fresh": True}, "OCCUPIED", OCCUPIED)
    assert d["blocked_by"] == "ENV_STALE"
    assert d["executed"] is False


def test_manual_lockout_prevents_action(controller):
    controller.config.app.control_mode = "active"
    controller.ir.locked_out = True
    d = controller.decide(FRESH, "OCCUPIED", OCCUPIED)
    assert d["blocked_by"] == "MANUAL_LOCKOUT"
    assert d["executed"] is False


def test_unresolved_room_does_nothing(controller):
    """담당 공간을 모르면 아무것도 하지 않는다."""
    controller.config.app.control_mode = "active"
    controller.storage.fetch_room_settings = lambda room_id: None
    d = controller.decide(FRESH, "OCCUPIED", OCCUPIED)
    assert d["executed"] is False
    assert controller.ir.sent_commands == []


def test_transmission_updates_state_for_interlocks(controller):
    """송신하면 기기 보호 조건이 볼 상태가 갱신돼야 한다."""
    controller.config.app.control_mode = "active"
    controller.decide(FRESH, "OCCUPIED", OCCUPIED)
    assert controller.cooling_on is True
    assert controller.last_on_at is not None
    assert controller.last_command_at is not None


# ----------------------------------------------------------------------
# 합성 재실자(히터)
# ----------------------------------------------------------------------

def test_히터는_판단마다_duty를_발행한다(controller):
    """노드 워치독이 이 발행을 먹고 산다. 판단 경로가 무엇이든 나가야 한다."""
    controller.decide(FRESH, "OCCUPIED", OCCUPIED)
    topics = [t for t, _ in controller.ir.published]
    assert controller.config.heater.topic in topics


def test_히터가_꺼져_있으면_duty_0을_보낸다(controller):
    # 기본값은 enabled=False 다. 그래도 발행은 해야 노드가 게이트웨이가
    # 살아 있음을 안다.
    controller.decide(FRESH, "OCCUPIED", OCCUPIED)
    heater_sends = [p for t, p in controller.ir.published
                    if t == controller.config.heater.topic]
    assert heater_sends == ["0"]


def test_공간을_못_찾아도_히터는_갱신된다(controller, monkeypatch):
    """DB 가 흔들려 공간을 못 찾아도 밤새 돌던 실험이 끊기면 안 된다.

    히터 발행이 멈추면 노드 워치독이 120초 뒤 히터를 끈다. 안전한 실패이긴
    하지만 그때까지 쌓은 가진 실험이 통째로 못 쓰게 된다. 그래서 히터
    갱신은 공간 조회보다 앞에 둔다.
    """
    monkeypatch.setattr(controller.storage, "fetch_room_settings", lambda _: None)
    result = controller.decide(FRESH, "OCCUPIED", OCCUPIED)
    assert result["reasons"] == ["ROOM_UNRESOLVED"]
    heater_sends = [p for t, p in controller.ir.published
                    if t == controller.config.heater.topic]
    assert heater_sends == ["0"]


# ----------------------------------------------------------------------
# 선냉방(precool) — origin/main 에서 가져와 공간 설정 구조에 맞춰 옮겼다.
#
# 원본은 storage.get_upcoming_schedule 과 config.yaml 목표 온도를 썼는데,
# 지금 컨트롤러는 fetch_active_schedule 과 DB 공간 설정을 본다. 검증하려는
# 것("리드타임이 남은 시간을 덮으면 미리 켠다")은 그대로다.
# ----------------------------------------------------------------------

class MockStorageWithSchedule(MockStorage):
    """예약이 하나 있는 경우. 선냉방 경로를 태우기 위한 목."""

    def __init__(self, minutes_until_start: float, target_temp: float):
        super().__init__()
        now = datetime.now(timezone.utc)
        starts_at = now + timedelta(minutes=minutes_until_start)
        self.schedule = {
            "schedule_id": 1,
            "starts_at": starts_at,
            "ends_at": starts_at + timedelta(hours=1),
            "target_temp": target_temp,
            "precooling_min": 0,
        }

    def fetch_active_schedule(self, room_id, now):
        return self.schedule


def test_예약이_리드타임_안으로_들어오면_미리_켠다(controller):
    """시험용 교정 모델 기준 27→24℃ 는 약 57분 걸린다. 예약이 40분 뒤면 지금
    켜야 한다 — 이것이 '예측 제어'의 최소 형태다."""
    controller.config.app.control_mode = "active"
    controller.storage = MockStorageWithSchedule(
        minutes_until_start=40, target_temp=24.0)
    d = controller.decide(FRESH, "EMPTY", EMPTY)
    assert d["decision_type"] == "precool"
    assert d["proposed_action"] == "COOL_24_AUTO"
    assert d["executed"] is True


def test_예약이_아직_멀면_켜지_않는다(controller):
    """같은 상황이라도 예약이 120분 뒤면 아직 켤 때가 아니다."""
    controller.config.app.control_mode = "active"
    controller.storage = MockStorageWithSchedule(
        minutes_until_start=120, target_temp=24.0)
    d = controller.decide(FRESH, "EMPTY", EMPTY)
    assert d["decision_type"] != "precool"
    assert d["executed"] is False


def test_히터_이력이_실제로_기록된다(controller):
    """정답 라벨은 이 기록이 전부다. 기록 호출은 예외를 삼키는 자리에 있어서
    (히터 제어를 막지 않으려고) 메서드 이름이 틀려도 조용히 넘어간다.
    그 침묵을 여기서 깬다."""
    controller.decide(FRESH, "OCCUPIED", OCCUPIED)
    assert len(controller.storage.heater_logs) == 1
    entry = controller.storage.heater_logs[0]
    assert entry["applied"] == 0
    assert entry["run_id"] is None


def test_실험이_돌면_그_duty가_기록된다(controller):
    from app.excitation import ExcitationPlan
    controller.config.heater.enabled = True
    plan = ExcitationPlan("t", ((0, 600.0), (40, 900.0)))
    controller.storage.experiment = {
        "run_id": 7,
        "plan_name": "t",
        "plan": plan.to_dict(),
        "started_at": datetime.now(timezone.utc) - timedelta(seconds=700),
        "ends_at": datetime.now(timezone.utc) + timedelta(seconds=800),
    }
    controller.decide(FRESH, "OCCUPIED", OCCUPIED)
    entry = controller.storage.heater_logs[-1]
    assert entry["requested"] == 40      # 700초 경과 -> 두 번째 구간
    assert entry["applied"] == 40
    assert entry["run_id"] == 7


def test_계획이_끝나면_실험을_닫는다(controller):
    from app.excitation import ExcitationPlan
    controller.config.heater.enabled = True
    plan = ExcitationPlan("t", ((40, 600.0),))
    controller.storage.experiment = {
        "run_id": 7, "plan_name": "t", "plan": plan.to_dict(),
        "started_at": datetime.now(timezone.utc) - timedelta(seconds=900),
        "ends_at": datetime.now(timezone.utc) - timedelta(seconds=300),
    }
    controller.decide(FRESH, "OCCUPIED", OCCUPIED)
    assert controller.storage.experiment is None
    assert controller.storage.heater_logs[-1]["applied"] == 0
