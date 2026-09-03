import logging
from typing import Dict, Any
from datetime import datetime, timezone
from app.models import EnvData, OccData, IrData
from app.storage import get_storage
from app.config import get_config
import json

logger = logging.getLogger(__name__)

class DataQuality:
    def __init__(self):
        self.storage = get_storage()
        self.last_seen: Dict[str, datetime] = {}
        self.latest_env: Dict[str, EnvData] = {}
        self.latest_occ: Dict[str, OccData] = {}

    def process_env(self, data: EnvData, raw_payload: str = "{}"):
        invalid_metrics = []
        if data.temperature_c is not None and not (-10 <= data.temperature_c <= 60):
            invalid_metrics.append("temperature")
            data.temperature_c = None
            
        if data.humidity_rh is not None and not (0 <= data.humidity_rh <= 100):
            invalid_metrics.append("humidity")
            data.humidity_rh = None
            
        if data.co2_ppm is not None and not (350 <= data.co2_ppm <= 10000):
            invalid_metrics.append("co2")
            data.co2_ppm = None

        if invalid_metrics:
            logger.warning(
                "범위 밖 환경값 제외 device=%s metrics=%s payload=%.200s",
                data.device_id, ",".join(invalid_metrics), raw_payload,
            )

        now = datetime.now(timezone.utc)
        self.last_seen["env"] = now
        self.latest_env[data.device_id] = data
        iso_now = now.isoformat()
        # 처음 보는 노드는 미배정 상태로 등록해 두면, 사용자가 프론트의
        # 공간·디바이스 화면에서 바로 공간에 배정할 수 있다.
        self.storage.register_device(data.device_id, "env", iso_now)

        if data.temperature_c is not None:
            self.storage.insert_sensor_reading(iso_now, data.device_id, "temperature", data.temperature_c, "OK", raw_payload)
        if data.humidity_rh is not None:
            self.storage.insert_sensor_reading(iso_now, data.device_id, "humidity", data.humidity_rh, "OK", raw_payload)
        if data.co2_ppm is not None:
            self.storage.insert_sensor_reading(iso_now, data.device_id, "co2", data.co2_ppm, "OK", raw_payload)

    def process_occ(self, data: OccData, raw_payload: str = "{}"):
        now = datetime.now(timezone.utc)
        self.last_seen["occ"] = now
        self.latest_occ[data.device_id] = data
        iso_now = now.isoformat()
        self.storage.register_device(data.device_id, "pir", iso_now)

        self.storage.insert_sensor_reading(iso_now, data.device_id, "pir", float(data.pir), "OK", raw_payload)
        self.storage.insert_sensor_reading(iso_now, data.device_id, "door", 1.0 if data.door == "open" else 0.0, "OK", raw_payload)

    def process_ir(self, data: IrData, raw_payload: str = "{}"):
        now = datetime.now(timezone.utc)
        self.last_seen["ir"] = now
        iso_now = now.isoformat()
        self.storage.register_device(data.device_id, "ir", iso_now)
        if data.code_hash != "unknown":
            self.storage.insert_ir_event(iso_now, "rx", data.protocol or "unknown", data.code_hash, "unknown", raw_payload)

    def is_env_stale(self) -> bool:
        config = get_config()
        stale_sec = config.control.env_data_stale_sec
        if "env" not in self.last_seen:
            return True
        now = datetime.now(timezone.utc)
        return (now - self.last_seen["env"]).total_seconds() > stale_sec

    def is_occ_stale(self) -> bool:
        config = get_config()
        stale_sec = config.control.occ_data_stale_sec
        if "occ" not in self.last_seen:
            return True
        now = datetime.now(timezone.utc)
        return (now - self.last_seen["occ"]).total_seconds() > stale_sec

_data_quality_instance = None

def get_data_quality() -> DataQuality:
    global _data_quality_instance
    if _data_quality_instance is None:
        _data_quality_instance = DataQuality()
    return _data_quality_instance
