import json
import logging
import re
from datetime import datetime, timezone, timedelta
from app.config import get_config
from app.storage import get_storage
from typing import Callable, Optional

logger = logging.getLogger(__name__)

_COOL_ACTION = re.compile(r"^COOL_(\d+)_")


def _target_temperature(action: str, fallback: float) -> float:
    """COOL_25_AUTO 같은 액션 이름에서 설정 온도를 뽑는다."""
    matched = _COOL_ACTION.match(action)
    return float(matched.group(1)) if matched else float(fallback)

class IRAdapter:
    def __init__(self, publish_func: Callable[[str, dict], None]):
        self.publish_func = publish_func
        self.config = get_config()
        self.storage = get_storage()
        
        self.manual_lockout_until: Optional[datetime] = None
        self.last_tx_hash: Optional[str] = None
        self.last_tx_time: Optional[datetime] = None

    def send_command(self, action: str):
        """제어 액션을 실제 하드웨어 토픽으로 내보낸다.

        노드는 두 가지를 따로 받는다.
          - 펠티어(냉각 릴레이): cooling_topic 에 평문 "ON" / "OFF"
          - 에어컨 IR        : aircon_topic 에 JSON

        예전 코드는 esp32/device/ir_01/cmd 로 보냈는데 이 토픽을 구독하는
        노드가 없어, active 모드로 올려도 명령이 어디에도 닿지 않았다.
        """
        # IR 코드 등록 여부로 냉방 자체를 막지 않는다.
        #
        # 실제로 동작하는 액추에이터는 펠티어 릴레이이고, 그것은 평문 ON/OFF
        # 한 줄이면 된다 — IR 프로파일이 필요 없다. 예전에는 config.ir.codes
        # 에 없는 액션(POWER_ON, COOL_23_AUTO 등)을 통째로 거절해서, 등록된
        # 세 온도(24/25/26) 밖의 명령은 릴레이까지 못 갔다. IR 프로파일은
        # 아직 전부 PLACEHOLDER 라 어차피 쏘지 못하는데, 그것 때문에 되는
        # 기능까지 막혀 있던 셈이다.
        code_hash = self.config.ir.codes.get(action)
        if code_hash is None:
            logger.info("IR 코드가 없는 액션 %s — 릴레이만 제어합니다", action)
            code_hash = f"{action}_NO_IR_PROFILE"
        now = datetime.now(timezone.utc)
        cooling_on = action != "POWER_OFF"

        # 1) 펠티어 릴레이 — 실증 프로토타입에서 실제로 동작하는 액추에이터
        self.publish_func(self.config.ir.cooling_topic, "ON" if cooling_on else "OFF")

        # 2) 에어컨 IR — IR 프로파일이 학습돼야 노드가 실제로 쏜다.
        #
        # vent_fan 은 냉각과 함께 켜도록 맞춰 두지만, 현재 펌웨어
        # (firmware/ir_01/ir_01.ino handleAirconControl)는 이 값을 status 로
        # 되돌려주기만 하고 GPIO 를 건드리지 않는다. 팬 전용 출력은 없다.
        # 실제 팬은 펠티어와 같은 12V 회선에 물려 릴레이(GPIO26)로 함께
        # 켜지므로, 팬을 돌리는 유일한 수단은 위 1) cooling_topic 이다.
        aircon_payload = {
            "aircon_power": "ON" if cooling_on else "OFF",
            "aircon_temp": _target_temperature(action, self.config.control.target_temperature_c),
            "aircon_mode": "cool",
            "vent_fan": "ON" if cooling_on else "OFF",
        }
        self.publish_func(self.config.ir.aircon_topic, aircon_payload)

        self.last_tx_hash = code_hash
        self.last_tx_time = now

        self.storage.insert_ir_event(
            now.isoformat(),
            "tx",
            "unknown",
            code_hash,
            "auto",
            json.dumps({"cooling": "ON" if cooling_on else "OFF", "aircon": aircon_payload},
                       ensure_ascii=False),
        )

    def handle_rx(self, code_hash: str, protocol: str):
        now = datetime.now(timezone.utc)
        
        # Check for self echo
        if self.last_tx_time and (now - self.last_tx_time).total_seconds() < 2.0:
            if code_hash == self.last_tx_hash:
                logger.info("IR self-echo ignored.")
                return

        # It's an external command
        lockout_sec = self.config.control.manual_lockout_sec
        self.manual_lockout_until = now + timedelta(seconds=lockout_sec)
        
        logger.info(f"External IR remote detected. Manual lockout until {self.manual_lockout_until}")
        self.storage.insert_system_event(now.isoformat(), "INFO", "MANUAL_LOCKOUT", f"External IR code {code_hash} received.")

    def is_locked_out(self) -> bool:
        if self.manual_lockout_until is None:
            return False
        if datetime.now(timezone.utc) > self.manual_lockout_until:
            self.manual_lockout_until = None
            return False
        return True
