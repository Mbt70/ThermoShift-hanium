import logging
import signal
import time
import threading
from datetime import datetime, timezone
from app.config import get_config
from app.storage import get_storage
from app.mqtt_adapter import MQTTAdapter
from app.data_quality import get_data_quality
from app.feature_engine import get_feature_engine
from app.occupancy_hmm import get_occupancy_hmm
from app.ir_adapter import IRAdapter
from app.controller import HVACController
import paho.mqtt.client as mqtt
from paho.mqtt.enums import CallbackAPIVersion
import json

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class EdgeNode:
    def __init__(self):
        self.config = get_config()
        logging.getLogger().setLevel(getattr(logging, self.config.app.log_level))
        
        self.storage = get_storage()
        self.mqtt_adapter = MQTTAdapter()
        self.dq = get_data_quality()
        self.fe = get_feature_engine()
        self.hmm = get_occupancy_hmm()
        
        self.client = mqtt.Client(callback_api_version=CallbackAPIVersion.VERSION2, client_id=self.config.mqtt.client_id)
        self.client.on_connect = self.on_connect
        self.client.on_message = self.on_message
        # 끊긴 이유를 남긴다. 이게 없으면 재접속이 반복돼도 원인을 알 수 없다
        # (실제로 2초마다 재접속하는 문제를 추적하는 데 며칠 걸릴 뻔했다).
        self.client.on_disconnect = self.on_disconnect
        
        self.ir = IRAdapter(self.publish_mqtt)
        self.controller = HVACController(self.ir)
        
        self.mqtt_adapter.register_callback(self._route_data)

    def publish_mqtt(self, topic: str, payload):
        """dict 는 JSON 으로, str 은 그대로 발행한다.

        냉각 릴레이 토픽은 평문 "ON"/"OFF" 를 받으므로 JSON 으로 감싸면 안 된다.
        """
        body = payload if isinstance(payload, str) else json.dumps(payload)
        self.client.publish(topic, body)

    def on_connect(self, client, userdata, flags, reason_code, properties):
        logger.info(f"Connected to MQTT broker with result code {reason_code}")
        for topic in self.config.mqtt.topics:
            self.client.subscribe(topic)

    def on_disconnect(self, client, userdata, flags, reason_code, properties):
        logger.warning("MQTT 연결 끊김 — reason_code=%s (%s)",
                       reason_code, getattr(reason_code, "getName", lambda: "?")())

    def on_message(self, client, userdata, msg):
        payload_str = msg.payload.decode('utf-8')
        self.mqtt_adapter.process_message(msg.topic, payload_str)

    def _route_data(self, data):
        from app.models import EnvData, OccData, IrData
        if isinstance(data, EnvData):
            self.dq.process_env(data)
        elif isinstance(data, OccData):
            self.dq.process_occ(data)
        elif isinstance(data, IrData):
            self.dq.process_ir(data)
            self.ir.handle_rx(data.code_hash, data.protocol or "unknown")

    def _drain_command_queue(self):
        """프론트에서 들어온 수동 제어 명령을 처리한다.

        API는 control_commands 에 pending 으로 넣기만 하고, 실제 IR 송신은
        여기서만 일어난다. 제어 명령이 두 곳에서 나가지 않도록 하기 위해서다.
        """
        room_id = self.storage.resolve_room_id()
        for command in self.storage.fetch_pending_commands(room_id):
            now = datetime.now(timezone.utc).isoformat()
            action = command["action"]

            if self.config.app.control_mode != "active":
                # shadow 모드에서는 실제로 쏘지 않는다. 사용자가 왜 반영되지
                # 않았는지 알 수 있도록 실패 사유를 남긴다.
                self.storage.mark_command(command["id"], "failed", "shadow_mode", now)
                logger.info("shadow 모드라 수동 명령 %s 를 전송하지 않음", action)
                continue

            if self.ir.is_locked_out():
                self.storage.mark_command(command["id"], "failed", "manual_lockout", now)
                logger.info("수동 조작 lockout 중이라 %s 를 전송하지 않음", action)
                continue

            if action not in self.config.ir.codes:
                self.storage.mark_command(command["id"], "failed", "command_failed", now)
                logger.warning("등록되지 않은 IR 코드: %s", action)
                continue

            try:
                self.ir.send_command(action)
            except Exception:
                self.storage.mark_command(command["id"], "failed", "command_failed", now)
                logger.exception("수동 명령 %s 전송 실패", action)
                continue

            self.controller.current_action = action
            self.storage.mark_command(command["id"], "sent", None, now)
            logger.info("수동 명령 %s 전송 완료", action)

    def run_loop(self):
        interval = self.config.control.decision_interval_sec
        logger.info("Starting Edge Control Loop")
        while True:
            try:
                self._drain_command_queue()
                features = self.fe.compute_features()
                state, probs, reasons = self.hmm.update(features)
                decision = self.controller.decide(
                    features, 
                    state, 
                    {"empty": probs[0], "transition": probs[1], "occupied": probs[2]}
                )
                logger.info(f"Decision: {decision}")
            except Exception as e:
                logger.error(f"Error in control loop: {e}", exc_info=True)
            time.sleep(interval)

    def start(self):
        self.client.connect(self.config.mqtt.host, self.config.mqtt.port, 60)
        self.client.loop_start()

        loop_thread = threading.Thread(target=self.run_loop, daemon=True)
        loop_thread.start()

        # SIGTERM 을 받아야 한다. 예전에는 KeyboardInterrupt(=SIGINT)만
        # 처리해서 systemd 의 stop 이나 timeout(1) 이 보내는 SIGTERM 에
        # 죽지 않았다. 그 결과 게이트웨이가 유령으로 남았고, 새로 띄운
        # 인스턴스와 **같은 MQTT client_id** 로 붙어 서로를 밀어냈다.
        # 브로커가 둘을 번갈아 끊어 2초마다 재접속이 반복됐다.
        self._stop = threading.Event()

        def _shutdown(signum, _frame):
            logger.info("신호 %s 수신 — 종료합니다", signal.Signals(signum).name)
            self._stop.set()

        signal.signal(signal.SIGTERM, _shutdown)
        signal.signal(signal.SIGINT, _shutdown)

        try:
            self._stop.wait()
        finally:
            logger.info("Stopping...")
            self.client.loop_stop()
            self.client.disconnect()

if __name__ == "__main__":
    node = EdgeNode()
    node.start()
