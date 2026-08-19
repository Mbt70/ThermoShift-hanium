import json
import logging
from datetime import datetime, timezone
from typing import Callable, Any, List
from app.models import EnvData, OccData, IrData
from app.storage import get_storage

logger = logging.getLogger(__name__)

class MQTTAdapter:
    def __init__(self):
        self.callbacks: List[Callable[[Any], None]] = []
        self.storage = get_storage()
        self.last_door_state = None

    def register_callback(self, cb: Callable[[Any], None]):
        self.callbacks.append(cb)

    def process_message(self, topic: str, payload_str: str):
        try:
            payload = json.loads(payload_str)
        except json.JSONDecodeError:
            logger.warning(f"Failed to decode JSON from {topic}")
            return

        now = datetime.now(timezone.utc)
        iso_now = now.isoformat()

        # Extract device_id
        device_id = payload.get("node")
        if not device_id:
            parts = topic.split('/')
            if len(parts) >= 3 and parts[0] == "esp32":
                device_id = parts[2]
            elif len(parts) >= 2:
                device_id = parts[1]
            else:
                device_id = "unknown"

        has_env = False
        has_occ = False
        has_ir = False

        # EnvData
        temp = payload.get("temperature") if payload.get("temperature") is not None else payload.get("temp_c")
        hum = payload.get("humidity") if payload.get("humidity") is not None else payload.get("humidity_rh")
        co2 = payload.get("co2") if payload.get("co2") is not None else payload.get("co2_ppm")
        
        if temp is not None or hum is not None or co2 is not None:
            has_env = True
            env_data = EnvData(
                device_id=device_id,
                timestamp=now,
                temperature_c=float(temp) if temp is not None else None,
                humidity_rh=float(hum) if hum is not None else None,
                co2_ppm=float(co2) if co2 is not None else None
            )
            for cb in self.callbacks:
                cb(env_data)
            
            # Storage is usually called after DataQuality check, but we store raw here too or in data_quality?
            # Instructions: "다음 범위를 벗어난 값은 invalid 처리하되 원본은 raw log로 남긴다."
            # So we let data_quality handle quality and storage.

        # OccData
        pir = None
        door = None
        if "pir_door" in payload or "pir_seat" in payload or "motion" in payload:
            pir_val = payload.get("motion", 0) or payload.get("pir_door", 0) or payload.get("pir_seat", 0)
            pir = bool(pir_val)
        
        if "door_main" in payload or "door_sub" in payload or "door_open" in payload:
            door_val = payload.get("door_open", 0) or payload.get("door_main", 0)
            door = "open" if door_val else "closed"

        if pir is not None or door is not None:
            has_occ = True
            door_event = False
            if door is not None:
                if self.last_door_state is not None and self.last_door_state != door:
                    door_event = True
                self.last_door_state = door

            occ_data = OccData(
                device_id=device_id,
                timestamp=now,
                pir=pir if pir is not None else False,
                door=door if door is not None else "unknown",
                door_event=door_event
            )
            for cb in self.callbacks:
                cb(occ_data)

        # IrData
        if "protocol" in payload or "code_hash" in payload or "raw" in payload:
            has_ir = True
            protocol = payload.get("protocol")
            code_hash = payload.get("code_hash", "unknown")
            raw = payload.get("raw")
            
            if code_hash != "unknown" or raw is not None:
                ir_data = IrData(
                    device_id=device_id,
                    timestamp=now,
                    protocol=protocol,
                    raw=raw,
                    code_hash=code_hash
                )
                for cb in self.callbacks:
                    cb(ir_data)
