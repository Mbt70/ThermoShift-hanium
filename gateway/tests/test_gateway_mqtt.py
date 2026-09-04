import logging
from datetime import datetime, timezone
from types import SimpleNamespace

from app.main import EdgeNode
from app.models import ActuatorStateData


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


def test_matching_relay_state_acknowledges_waiting_command():
    node = EdgeNode.__new__(EdgeNode)
    acknowledged = []
    audit = []
    node.storage = SimpleNamespace(
        acknowledge_command=lambda command_id, state, at: acknowledged.append(
            (command_id, state, at)
        ) or True,
        insert_ir_event=lambda *args: audit.append(args),
        register_device=lambda *args: None,
    )
    node.controller = SimpleNamespace(cooling_on=False, current_action="POWER_OFF")
    node._awaiting_relay_ack = {
        "command_id": 17,
        "expected_state": "ON",
        "deadline": datetime.now(timezone.utc),
    }

    node._route_data(ActuatorStateData(
        device_id="ir_01",
        timestamp=datetime.now(timezone.utc),
        actuator="cooling",
        state="ON",
        raw_payload="ON",
    ))

    assert acknowledged[0][0:2] == (17, "ON")
    assert node._awaiting_relay_ack is None
    assert node.controller.cooling_on is True
    assert audit


def test_mismatched_relay_state_does_not_acknowledge_command():
    node = EdgeNode.__new__(EdgeNode)
    acknowledged = []
    node.storage = SimpleNamespace(
        acknowledge_command=lambda *args: acknowledged.append(args),
        insert_ir_event=lambda *args: None,
        register_device=lambda *args: None,
    )
    node.controller = SimpleNamespace(cooling_on=True, current_action="COOL_24_AUTO")
    waiting = {
        "command_id": 18,
        "expected_state": "OFF",
        "deadline": datetime.now(timezone.utc),
    }
    node._awaiting_relay_ack = waiting

    node._route_data(ActuatorStateData(
        device_id="ir_01",
        timestamp=datetime.now(timezone.utc),
        actuator="cooling",
        state="ON",
        raw_payload="ON",
    ))

    assert acknowledged == []
    assert node._awaiting_relay_ack == waiting
