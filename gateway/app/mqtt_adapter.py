import json
import logging
import time
from datetime import datetime, timezone
from typing import Callable, Any, Dict, List
from app.models import EnvData, OccData, IrData
from app.storage import get_storage

logger = logging.getLogger(__name__)

class MQTTAdapter:
    # 같은 토픽의 파싱 실패를 이 간격으로만 로그에 남긴다.
    # 펌웨어가 깨진 JSON 을 주기적으로 보내면 로그가 그것만으로 가득 찬다.
    DECODE_WARNING_INTERVAL_SEC = 300

    def __init__(self):
        self.callbacks: List[Callable[[Any], None]] = []
        self.storage = get_storage()
        self.last_door_state = None
        self._last_decode_warning: Dict[str, float] = {}

    def register_callback(self, cb: Callable[[Any], None]):
        self.callbacks.append(cb)

    # JSON 이 아닌 것이 정상인 토픽. 냉방 릴레이 상태는 평문 "ON"/"OFF" 로
    # 오간다(firmware/ir_01 참고). 게이트웨이는 thermoshift/# 를 통째로
    # 구독하므로 이 토픽도 받게 되는데, 파싱 실패로 로그를 채울 일이 아니다.
    PLAINTEXT_TOPICS = ("thermoshift/ir_01/cooling/state",
                        "thermoshift/ir_01/cooling/cmd")

    def process_message(self, topic: str, payload_str: str):
        if topic in self.PLAINTEXT_TOPICS:
            return

        try:
            payload = json.loads(payload_str)
        except json.JSONDecodeError as exc:
            now = time.monotonic()
            last = self._last_decode_warning.get(topic, 0.0)
            if now - last >= self.DECODE_WARNING_INTERVAL_SEC:
                self._last_decode_warning[topic] = now
                # 페이로드 앞부분을 함께 남겨야 펌웨어의 어느 필드가
                # 깨졌는지 바로 알 수 있다.
                logger.warning(
                    "JSON 파싱 실패 %s: %s | payload=%.120s",
                    topic, exc, payload_str,
                )
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
        #
        # 노드는 연결되지 않은 센서를 -1 로 보낸다. 예전 코드는
        #   payload.get("motion", 0) or payload.get("pir_door", 0) or payload.get("pir_seat", 0)
        # 처럼 or 로 이어 붙였는데, pir_door 가 0(움직임 없음)이면 -1 이
        # 선택되고 bool(-1) == True 라 항상 '재실' 로 읽혔다. 실제로
        # 저장된 PIR 값 110건이 전부 1.0 이었다.
        # 이제 음수는 '센서 없음' 으로 보고 판단에서 제외한다.
        pir = None
        door = None

        def _sensor_flags(*keys) -> list[float]:
            flags = []
            for key in keys:
                value = payload.get(key)
                if isinstance(value, bool):
                    flags.append(int(value))
                elif isinstance(value, (int, float)) and value >= 0:
                    flags.append(float(value))
            return flags

        PIR_KEYS = ("motion", "pir_door", "pir_seat")
        if any(key in payload for key in PIR_KEYS):
            flags = _sensor_flags(*PIR_KEYS)
            # 쓸 수 있는 PIR 이 하나도 없으면 판단하지 않는다(None).
            # 억지로 False 를 넣으면 '사람 없음' 으로 읽혀 공실 판정이 앞당겨진다.
            pir = any(flag > 0 for flag in flags) if flags else None

        # door_sub 는 아직 어떤 문(門)에 붙어 있는지 확인되지 않아 판단에
        # 넣지 않는다. 하드웨어 배치가 확정되면 여기에 더한다.
        DOOR_KEYS = ("door_open", "door_main")
        if any(key in payload for key in ("door_open", "door_main", "door_sub")):
            flags = _sensor_flags(*DOOR_KEYS)
            door = ("open" if any(flag > 0 for flag in flags) else "closed") if flags else None

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
