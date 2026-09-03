from app.models import EnvData, OccData
from app.mqtt_adapter import MQTTAdapter


def adapter_with_capture():
    adapter = MQTTAdapter.__new__(MQTTAdapter)
    captured = []
    adapter.callbacks = [captured.append]
    adapter.storage = None
    adapter.last_door_state = {}
    adapter._last_decode_warning = {}
    adapter._recent_env = {}
    return adapter, captured


def test_environment_message_keeps_original_payload():
    adapter, captured = adapter_with_capture()
    raw = '{"node":"env_01","temperature":24.52,"humidity":56.47,"co2":1226}'

    adapter.process_message("thermoshift/env_01/data", raw)

    assert len(captured) == 1
    assert isinstance(captured[0], EnvData)
    assert captured[0].raw_payload == raw


def test_door_transition_state_is_isolated_per_device():
    adapter, captured = adapter_with_capture()
    adapter.process_message(
        "thermoshift/occ/a", '{"node":"a","pir_door":0,"door_main":0}'
    )
    adapter.process_message(
        "thermoshift/occ/b", '{"node":"b","pir_door":0,"door_main":1}'
    )
    adapter.process_message(
        "thermoshift/occ/a", '{"node":"a","pir_door":0,"door_main":1}'
    )

    events = [item for item in captured if isinstance(item, OccData)]
    assert [item.door_event for item in events] == [False, False, True]
