import logging
import os
import signal
import sys
import time
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path

_REPOSITORY_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_REPOSITORY_ROOT) not in sys.path:
    # ml/ 은 저장소 루트에 있다. 게이트웨이는 gateway/ 를 작업 디렉터리로
    # 삼아 `python -m app.main` 으로 뜨므로(scripts/services.sh), 다른
    # 진입점(web/main.py 등)과 같은 방식으로 루트를 sys.path 에 추가한다.
    sys.path.insert(0, str(_REPOSITORY_ROOT))

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
        
        # client_id 에 프로세스마다 다른 꼬리를 붙인다.
        #
        # 고정 ID 를 쓰면 같은 ID 로 붙은 다른 클라이언트와 브로커가 서로를
        # 밀어낸다. MQTT 규격상 나중에 붙은 쪽이 먼저 붙은 쪽을 끊기 때문에,
        # 둘이 1초 간격으로 무한히 재접속하며 그 사이 메시지를 잃는다.
        # 실제로 이 문제로 게이트웨이가 초당 한 번씩 재접속했고, 원인이
        # (1) 종료되지 않고 남은 이전 인스턴스와 (2) 브로커에 남은 유령
        # 세션이었다. 로그에는 "Connected" 만 반복돼 원인이 드러나지 않는다.
        #
        # 이 게이트웨이는 clean session 으로 붙고 LWT 도 쓰지 않으므로 ID 가
        # 매번 달라져도 잃는 것이 없다. config 의 값은 접두사로 남겨
        # 브로커 로그에서 사람이 알아볼 수 있게 한다.
        client_id = f"{self.config.mqtt.client_id}-{uuid.uuid4().hex[:8]}"
        logger.info("MQTT client_id: %s", client_id)
        self.client = mqtt.Client(
            callback_api_version=CallbackAPIVersion.VERSION2, client_id=client_id)
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

            # 수동 명령을 실행해도 되는지는 두 가지가 함께 정한다.
            #   config.yaml  안전 상한 (shadow 면 무조건 금지)
            #   rooms.control_mode  사용자가 화면에서 고른 모드
            # monitoring 은 "보기만 한다" 는 뜻이므로 수동 명령도 실행하지 않는다.
            room = self.storage.fetch_room_settings(room_id)
            room_mode = room["control_mode"] if room else "monitoring"
            if not self.controller.manual_allowed(room_mode):
                reason = ("shadow_mode" if self.config.app.control_mode != "active"
                          else "monitoring_mode")
                self.storage.mark_command(command["id"], "failed", reason, now)
                logger.info("수동 명령 %s 미전송 (%s, 공간 모드=%s)",
                            action, reason, room_mode)
                continue

            if self.ir.is_locked_out():
                self.storage.mark_command(command["id"], "failed", "manual_lockout", now)
                logger.info("수동 조작 lockout 중이라 %s 를 전송하지 않음", action)
                continue

            try:
                self.ir.send_command(action)
            except Exception:
                self.storage.mark_command(command["id"], "failed", "command_failed", now)
                logger.exception("수동 명령 %s 전송 실패", action)
                continue

            # 컨트롤러 상태를 함께 갱신해야 다음 자동 판단이 "지금 켜져 있다"
            # 는 것을 안다. 예전에는 current_action 만 바꿔서, 수동으로 켠 뒤
            # 최소 가동시간 같은 기기 보호 조건이 동작하지 않았다.
            self.controller._note_transmission(action, datetime.now(timezone.utc))
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
            # 커넥션 풀을 닫지 않으면 psycopg 의 워커 스레드가 살아 있어
            # 인터프리터가 끝나지 않는다. 실제로 SIGTERM 을 처리하고
            # "Stopping..." 까지 찍은 뒤에도 프로세스가 남아, 다음 인스턴스와
            # MQTT client_id 를 놓고 다투는 원인이 됐다.
            self.storage.close()
            logger.info("종료 완료")

        # 정리가 끝났는데도 인터프리터가 남는다. paho 와 psycopg 풀이 띄운
        # 스레드 중 일부가 비데몬이라 파이썬이 그것들을 기다리기 때문이다.
        # 그대로 두면 프로세스가 유령으로 남아 다음 인스턴스와 MQTT
        # client_id 를 놓고 다투고, systemd 는 TimeoutStopSec 만큼 기다렸다가
        # SIGKILL 로 죽인다(그동안 재시작이 지연된다).
        #
        # 위에서 연결과 커넥션 풀을 이미 닫았으므로 더 정리할 것이 없다.
        # os._exit 로 즉시 끝낸다.
        os._exit(0)

if __name__ == "__main__":
    node = EdgeNode()
    node.start()
