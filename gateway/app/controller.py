import logging
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any, Optional

_GATEWAY_APP_DIR = Path(__file__).resolve().parent
_REPOSITORY_ROOT = _GATEWAY_APP_DIR.parent.parent
if str(_REPOSITORY_ROOT) not in sys.path:
    # ml/ 은 저장소 루트에 있고, 게이트웨이는 gateway/ 를 작업 디렉터리로
    # 삼아 `python -m app.main` 으로 뜬다 (scripts/services.sh). 이 상태로는
    # ml.* 이 안 보이므로, web/main.py 등 다른 진입점과 같은 방식으로
    # 저장소 루트를 sys.path 에 추가한다.
    sys.path.insert(0, str(_REPOSITORY_ROOT))

from app.config import get_config
from app.storage import get_storage
from app.ir_adapter import IRAdapter
from app.data_quality import get_data_quality
from app.feature_engine import get_feature_engine
from app.occupancy_hmm import get_occupancy_hmm
from app.policy import PolicyConfig, PolicyInput, ScheduleWindow, decide as policy_decide

logger = logging.getLogger(__name__)

_THERMAL_PARAMS_PATH = _REPOSITORY_ROOT / "ml" / "params" / "thermal.json"

# gateway/app/storage.py 의 _CONTROL_MODES 와 같은 매핑. policy.py 는 DB
# 어휘(monitoring/manual/rule/mpc)를 쓰고, 이 프로젝트 설정은 게이트웨이
# 자체 어휘(shadow/active)를 쓰기 때문에 판단 직전에 변환이 필요하다.
_POLICY_CONTROL_MODE = {
    "shadow": "monitoring",
    "active": "rule",
    "manual_lockout": "manual",
    "failsafe": "monitoring",
}


def _load_thermal_model():
    """열모델을 불러온다. 교정 파일이 없으면 미교정 기본값으로 시작한다.

    ml 패키지 자체를 못 불러오는 극단적인 경우(sys.path 문제 등)에도
    게이트웨이 전체가 죽으면 안 되므로, 그럴 땐 None 을 돌려주고
    policy.decide() 가 선냉방 없이 판단하게 둔다.
    """
    try:
        from ml.thermal_model import ThermalModel
    except ImportError:
        logger.warning("ml 패키지를 불러올 수 없어 선냉방(precool) 없이 동작합니다")
        return None
    try:
        model = ThermalModel.load(_THERMAL_PARAMS_PATH)
        logger.info("열모델 로드: 교정됨 (r2=%s)", model.r2)
        return model
    except (FileNotFoundError, OSError, ValueError):
        logger.info("열모델 교정 파일이 없어 기본값(미교정 가정치)으로 시작합니다")
        return ThermalModel()


class HVACController:
    def __init__(self, ir_adapter: IRAdapter):
        self.config = get_config()
        self.storage = get_storage()
        self.ir = ir_adapter
        self.thermal = _load_thermal_model()

        self.last_on_time: Optional[datetime] = None
        self.last_off_time: Optional[datetime] = None
        self.last_command_time: Optional[datetime] = None
        self.current_action: str = "POWER_OFF"
        self.last_decision_time: Optional[datetime] = None

    def _policy_config(self) -> PolicyConfig:
        c = self.config.control
        # policy.py 는 target ± tolerance 로 대칭 구간을 쓰는데, 이 프로젝트
        # 설정(config.yaml)은 냉방 on/off 온도를 따로 갖는다(비대칭일 수
        # 있음). on 쪽 폭(냉방을 켜는 상한까지의 거리)을 tolerance 로 쓴다 -
        # 두 기준 다 "이 이상 더우면 켠다"는 같은 의미라서 자연스럽게 맞고,
        # 안전 쪽(더 빨리 켜는 쪽)에 맞추는 편이 낫다.
        tolerance = max(c.cooling_on_temperature_c - c.target_temperature_c, 0.1)
        return PolicyConfig(
            target_temp_c=c.target_temperature_c,
            temp_tolerance_c=tolerance,
            setback_delta_c=tolerance,
            cooling_on_duration_sec=c.cooling_on_duration_sec,
            cooling_off_duration_sec=c.cooling_off_duration_sec,
            minimum_on_time_sec=c.minimum_on_time_sec,
            minimum_off_time_sec=c.minimum_off_time_sec,
            command_rate_limit_sec=c.command_rate_limit_sec,
            co2_warning_ppm=c.co2_ventilation_warning_ppm,
            co2_critical_ppm=c.co2_critical_ppm,
        )

    def _schedule_window(self, room_id: Optional[int], now: datetime) -> Optional[ScheduleWindow]:
        if room_id is None:
            return None
        row = self.storage.get_upcoming_schedule(room_id, now)
        if row is None:
            return None
        # schedules.start_time/end_time 은 timezone 정보가 없는 time 컬럼이다.
        # DB의 나머지 시각 컬럼은 전부 UTC(timestamptz, PGTZ=UTC)라서 같은
        # 규약을 따른다고 가정한다. 예약을 "한국 현지 시각"으로 입력하는
        # 화면이 생기면 여기 +/-9시간 보정이 필요해질 수 있다 - 지금은 그런
        # 입력 경로가 없어 확인이 안 된다.
        starts_at = datetime.combine(now.date(), row["start_time"], tzinfo=timezone.utc)
        ends_at = datetime.combine(now.date(), row["end_time"], tzinfo=timezone.utc)
        return ScheduleWindow(
            starts_at=starts_at,
            ends_at=ends_at,
            target_temp_c=float(row["target_temp"]),
            schedule_id=row["schedule_id"],
        )

    def decide(self, features: Dict[str, Any], occupancy_state: str, p_occ: Dict[str, float]) -> dict:
        now = datetime.now(timezone.utc)
        self.last_decision_time = now

        dq = get_data_quality()
        env_data = next(iter(dq.latest_env.values()), None)
        temp_c = env_data.temperature_c if env_data else None
        co2_ppm = env_data.co2_ppm if env_data else None

        fe = get_feature_engine()
        locked_out = self.ir.is_locked_out()
        room_id = self.storage.resolve_room_id()

        policy_input = PolicyInput(
            now=now,
            temperature_c=temp_c,
            co2_ppm=co2_ppm,
            temp_history=fe.temp_history,
            occupancy_state=occupancy_state,
            p_occupied=p_occ.get("occupied", 0.0),
            current_action=self.current_action,
            cooling_on=self.current_action != "POWER_OFF",
            last_on_at=self.last_on_time,
            last_off_at=self.last_off_time,
            last_command_at=self.last_command_time,
            locked_out=locked_out,
            env_fresh=features["env_fresh"],
            occ_fresh=features.get("occ_fresh", True),
            schedule=self._schedule_window(room_id, now),
            control_mode=_POLICY_CONTROL_MODE.get(self.config.app.control_mode, "monitoring"),
            thermal=self.thermal,
        )

        decision = policy_decide(policy_input, self._policy_config())

        executed = False
        if decision.execute and decision.action != self.current_action:
            self.ir.send_command(decision.action)
            executed = True
            self.current_action = decision.action
            self.last_command_time = now
            if decision.action == "POWER_OFF":
                self.last_off_time = now
            else:
                self.last_on_time = now

        if decision.blocked_by == "CO2_CRITICAL":
            self.storage.insert_system_event(
                now.isoformat(), "CRITICAL", "CO2_ALERT", f"CO2 reached {co2_ppm} ppm"
            )

        result = {
            "timestamp": now.isoformat(),
            "control_mode": self.config.app.control_mode,
            "occupancy_state": occupancy_state,
            "occupancy_probabilities": p_occ,
            "temperature_c": temp_c,
            "co2_ppm": co2_ppm,
            "decision_type": decision.decision_type,
            "proposed_action": decision.action,
            "target_temp_c": decision.target_temp_c,
            "executed": executed,
            "reason_codes": decision.reasons,
            "blocked_by": decision.blocked_by,
        }

        self.storage.insert_control_decision(
            now.isoformat(),
            self.config.app.control_mode,
            decision.action,
            executed,
            occupancy_state,
            temp_c,
            co2_ppm,
            decision.reasons,
            room_id=room_id,
            estimate_id=get_occupancy_hmm().last_estimate_id,
            decision_type=decision.decision_type,
            target_temp=decision.target_temp_c,
        )

        return result
