import logging
from datetime import datetime, timezone, timedelta
from app.config import get_config
from app.storage import get_storage
from typing import Callable, Optional

logger = logging.getLogger(__name__)

class IRAdapter:
    def __init__(self, publish_func: Callable[[str, dict], None]):
        self.publish_func = publish_func
        self.config = get_config()
        self.storage = get_storage()
        
        self.manual_lockout_until: Optional[datetime] = None
        self.last_tx_hash: Optional[str] = None
        self.last_tx_time: Optional[datetime] = None

    def send_command(self, action: str):
        if action not in self.config.ir.codes:
            logger.warning(f"No IR code registered for {action}")
            return
            
        code_hash = self.config.ir.codes[action]
        # In a real scenario, we'd send the raw or hash to the esp32 topic
        payload = {
            "cmd": "send_ir",
            "code_hash": code_hash
        }
        self.publish_func("esp32/device/ir_01/cmd", payload)
        
        now = datetime.now(timezone.utc)
        self.last_tx_hash = code_hash
        self.last_tx_time = now
        
        self.storage.insert_ir_event(
            now.isoformat(),
            "tx",
            "unknown",
            code_hash,
            "auto",
            str(payload)
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
