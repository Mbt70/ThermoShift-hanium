"""제어 오케스트레이션 — 판단은 policy 에 맡기고 부작용만 담당한다.

예전 구조와 달라진 점
---------------------
판단·IR 송신·DB 기록·상태 보관이 한 덩어리였다. 이제 "무엇을 할지" 는
app/policy.py 의 순수 함수가 정하고, 여기서는 그 결과를 실제로 내보내고
기록한다. 덕분에 판단 로직은 MQTT·DB 없이 시험할 수 있다
(gateway/tests/test_policy.py).

대시보드와의 연결
-----------------
설정을 config.yaml 이 아니라 **DB(rooms 표)** 에서 매 주기 다시 읽는다.
사용자가 화면에서 목표 온도나 제어 모드를 바꾸면 다음 판단부터 곧바로
반영된다. 예전에는 config.yaml 만 봐서 화면 조작이 아무 일도 하지 않았다.

    rooms.control_mode   monitoring  판단만 기록, 송신 안 함
                         manual      자동 제어 없음, 수동 명령만 실행
                         rule        규칙 기반 자동 제어
                         mpc         (미구현) 현재는 rule 과 동일하게 동작

config.yaml 의 control_mode 는 **안전 상한**으로만 쓴다. shadow 로 두면
DB 가 무엇이든 절대 송신하지 않는다. 실증 공간에 사람이 있을 때 확실히
멈춰 두는 수단이 필요하기 때문이다.
"""

import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from app.config import get_config
from app.data_quality import get_data_quality
from app.feature_engine import get_feature_engine
from app.ir_adapter import IRAdapter
from app.heater import HeaterController
from app.occupancy_hmm import get_occupancy_hmm
from app.policy import (PolicyConfig, PolicyInput, ScheduleWindow, decide)
from app.storage import get_storage
from app.thermal import load_thermal_model

logger = logging.getLogger(__name__)

# DB 의 제어 모드 → 자동 제어를 해도 되는가
_AUTOMATIC_MODES = {"rule", "mpc"}
# 수동 명령(큐)을 실행해도 되는가
_MANUAL_ALLOWED = {"manual", "rule", "mpc"}


class HVACController:
    def __init__(self, ir_adapter: IRAdapter):
        self.config = get_config()
        self.storage = get_storage()
        self.ir = ir_adapter

        self.current_action: str = "POWER_OFF"
        self.cooling_on: bool = False
        self.last_on_at: Optional[datetime] = None
        self.last_off_at: Optional[datetime] = None
        self.last_command_at: Optional[datetime] = None
        self.thermal = load_thermal_model()

        # 합성 재실자(히팅패드). 목업이 12L 라 사람을 넣을 수 없어서,
        # 재실 열부하를 히터 duty 로 만든다. app/heater.py 참고.
        self.heater = HeaterController(
            publish_func=ir_adapter.publish_func,
            topic=self.config.heater.topic,
        )

    # ------------------------------------------------------------------
    @property
    def transmit_allowed(self) -> bool:
        """config.yaml 의 안전 상한. shadow 면 무슨 일이 있어도 송신하지 않는다."""
        return self.config.app.control_mode == "active"

    def manual_allowed(self, room_mode: str) -> bool:
        return self.transmit_allowed and room_mode in _MANUAL_ALLOWED

    # ------------------------------------------------------------------
    def _policy_config(self, room: Dict[str, Any]) -> PolicyConfig:
        """DB 의 공간 설정과 config.yaml 의 기기 보호값을 합친다.

        사람이 화면에서 정하는 것(목표 온도·허용폭·CO2 한계)은 DB 를 따르고,
        압축기 보호처럼 기기에 매인 값은 config.yaml 을 따른다.
        """
        c = self.config.control
        return PolicyConfig(
            target_temp_c=room["target_temp"],
            temp_tolerance_c=room["temp_tolerance"],
            cooling_on_duration_sec=c.cooling_on_duration_sec,
            cooling_off_duration_sec=c.cooling_off_duration_sec,
            minimum_on_time_sec=c.minimum_on_time_sec,
            minimum_off_time_sec=c.minimum_off_time_sec,
            command_rate_limit_sec=c.command_rate_limit_sec,
            co2_warning_ppm=float(room["co2_limit"]),
            co2_critical_ppm=c.co2_critical_ppm,
        )

    def _schedule_window(self, room_id, now) -> Optional[ScheduleWindow]:
        s = self.storage.fetch_active_schedule(room_id, now)
        if s is None:
            return None
        return ScheduleWindow(starts_at=s["starts_at"], ends_at=s["ends_at"],
                              target_temp_c=s["target_temp"],
                              schedule_id=s["schedule_id"])

    # ------------------------------------------------------------------
    def decide(self, features: Dict[str, Any], occupancy_state: str,
               p_occ: Dict[str, float]) -> dict:
        now = datetime.now(timezone.utc)
        dq = get_data_quality()

        # 공간 설정을 읽기 **전에** 부른다. 히터는 방 설정과 무관한 실험
        # 부하다. DB 가 잠깐 흔들려 공간을 못 찾았다는 이유로 밤새 돌던
        # 식별 실험이 끊기면 안 된다(노드 워치독이 120초 뒤 히터를 끈다).
        # 안전 차단은 _tick_heater 안에 그대로 있으므로 이르게 불러도
        # 위험하지 않다.
        self._tick_heater(dq, now)

        room_id = self.storage.resolve_room_id()
        room = self.storage.fetch_room_settings(room_id)

        if room is None:
            # 담당 공간을 모르면 아무것도 하지 않는다. 어느 방을 식힐지
            # 모르는 채로 냉방을 켜는 것보다 멈춰 있는 편이 낫다.
            logger.warning("담당 공간을 찾지 못했습니다 — 판단을 건너뜁니다")
            return {"decision_type": "off", "action": self.current_action,
                    "executed": False, "reasons": ["ROOM_UNRESOLVED"]}

        room_mode = room["control_mode"]
        fe = get_feature_engine()
        env = next(iter(dq.latest_env.values()), None)

        # rules/mpc 가 아니면 정책에 관측 모드로 알려 준다. 그러면 정책이
        # 판단은 그대로 하되 송신하지 말라고 표시해 준다(blocked_by).
        effective_mode = room_mode if room_mode in _AUTOMATIC_MODES else "monitoring"
        if not self.transmit_allowed:
            effective_mode = "monitoring"

        inp = PolicyInput(
            now=now,
            temperature_c=env.temperature_c if env else None,
            co2_ppm=env.co2_ppm if env else None,
            temp_history=list(fe.temp_history),
            occupancy_state=occupancy_state,
            p_occupied=p_occ.get("occupied", 0.0),
            current_action=self.current_action,
            cooling_on=self.cooling_on,
            last_on_at=self.last_on_at,
            last_off_at=self.last_off_at,
            last_command_at=self.last_command_at,
            locked_out=self.ir.is_locked_out(),
            env_fresh=features["env_fresh"],
            occ_fresh=features["occ_fresh"],
            schedule=self._schedule_window(room_id, now),
            control_mode=effective_mode,
            thermal=self.thermal,
        )

        result = decide(inp, self._policy_config(room))

        executed = False
        if result.execute:
            try:
                self.ir.send_command(result.action)
                executed = True
                self._note_transmission(result.action, now)
            except Exception:
                logger.exception("제어 명령 %s 전송 실패", result.action)
                result.reasons.append("TRANSMIT_FAILED")

        if room_mode == "mpc":
            # 아직 MPC 가 없다. 사용자가 화면에서 '예측 제어' 를 골랐는데
            # 실제로는 규칙 제어가 돌고 있다는 사실을 기록에 남긴다.
            result.reasons.append("MPC 미구현 — 규칙 제어로 동작")

        # 기록에는 **공간의 제어 모드**를 남긴다. 게이트웨이 config 의
        # shadow/active 는 안전 스위치일 뿐이고, "이 판단이 어떤 운전 방식에서
        # 나왔는가" 는 사용자가 고른 모드다. 나중에 baseline(monitoring) 대비
        # rule 구간을 나눠 KPI 를 계산할 때 이 값이 기준이 된다.
        self.storage.insert_control_decision(
            now.isoformat(),
            effective_mode,
            result.action,
            executed,
            occupancy_state,
            inp.temperature_c,
            inp.co2_ppm,
            result.reasons,
            room_id=room_id,
            estimate_id=get_occupancy_hmm().last_estimate_id,
            decision_type=result.decision_type,
        )

        return {
            "timestamp": now.isoformat(),
            "room": room["name"],
            "room_mode": room_mode,
            "decision_type": result.decision_type,
            "occupancy_state": occupancy_state,
            "temperature_c": inp.temperature_c,
            "co2_ppm": inp.co2_ppm,
            "target_temp_c": result.target_temp_c,
            "proposed_action": result.action,
            "executed": executed,
            "blocked_by": result.blocked_by,
            "reason_codes": result.reasons,
        }

    # ------------------------------------------------------------------
    def _tick_heater(self, dq, now: datetime) -> None:
        """합성 재실자 열원을 매 판단 주기마다 갱신한다.

        duty 가 그대로여도 매번 발행한다. 노드의 워치독(120초)이 이
        발행을 먹고 살기 때문이다. 게이트웨이가 죽으면 발행이 끊기고
        노드가 스스로 히터를 끈다 — 그러라고 만든 구조다.

        config.app.control_mode 의 shadow 상한과는 **무관하게** 돈다.
        그 상한은 '에어컨을 건드리지 말라'는 뜻이고, 히터는 제어 출력이
        아니라 실험 부하다. 오히려 shadow(냉방 정지) + 히터 가동이
        개루프 열모델 식별에 쓰는 정확한 조합이다. 히터를 멈추는 스위치는
        config.heater.enabled 하나뿐이다.
        """
        env = next(iter(dq.latest_env.values()), None)
        last_seen = dq.last_seen.get("env")
        age_sec = (now - last_seen).total_seconds() if last_seen else None

        if not self.config.heater.enabled:
            self.heater.request_duty(0)

        self.heater.tick(env.temperature_c if env else None, age_sec)

    def _note_transmission(self, action: str, now: datetime) -> None:
        """송신 직후 상태를 갱신한다. 기기 보호 조건이 이 값들을 본다."""
        self.current_action = action
        self.last_command_at = now
        if action == "POWER_OFF":
            self.cooling_on = False
            self.last_off_at = now
        else:
            self.cooling_on = True
            self.last_on_at = now
