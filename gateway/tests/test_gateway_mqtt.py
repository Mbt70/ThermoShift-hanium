import logging
from types import SimpleNamespace

from app.main import EdgeNode


def test_mqtt_callback_failure_does_not_escape(caplog):
    """DB 재시작 등 메시지 한 건의 실패가 Paho 수집 스레드를 죽이면 안 된다."""
    node = EdgeNode.__new__(EdgeNode)

    class FailingAdapter:
        def process_message(self, topic, payload):
            raise RuntimeError("temporary storage failure")

    node.mqtt_adapter = FailingAdapter()
    message = SimpleNamespace(topic="thermoshift/env_01/data", payload=b'{"co2": 800}')

    with caplog.at_level(logging.ERROR):
        node.on_message(None, None, message)

    assert "다음 메시지부터 계속 수집" in caplog.text


def test_invalid_utf8_does_not_escape(caplog):
    node = EdgeNode.__new__(EdgeNode)
    node.mqtt_adapter = SimpleNamespace(process_message=lambda *_: None)
    message = SimpleNamespace(topic="thermoshift/env_01/data", payload=b"\xff")

    with caplog.at_level(logging.ERROR):
        node.on_message(None, None, message)

    assert "MQTT 메시지 처리 실패" in caplog.text
