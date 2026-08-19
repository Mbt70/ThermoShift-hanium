import sys
import time
import json
from datetime import datetime, timezone
from app.mqtt_adapter import MQTTAdapter
from app.data_quality import get_data_quality
from app.feature_engine import get_feature_engine
from app.occupancy_hmm import get_occupancy_hmm
from app.controller import HVACController
from app.ir_adapter import IRAdapter
import logging

logging.basicConfig(level=logging.INFO)

def run_replay():
    # Setup components
    mqtt = MQTTAdapter()
    dq = get_data_quality()
    fe = get_feature_engine()
    hmm = get_occupancy_hmm()
    
    def mock_publish(topic, payload):
        print(f"[REPLAY] TX -> {topic}: {payload}")
        
    ir = IRAdapter(mock_publish)
    ctrl = HVACController(ir)
    
    def route_data(data):
        from app.models import EnvData, OccData, IrData
        if isinstance(data, EnvData): dq.process_env(data)
        elif isinstance(data, OccData): dq.process_occ(data)
        elif isinstance(data, IrData): 
            dq.process_ir(data)
            ir.handle_rx(data.code_hash, data.protocol or "unknown")

    mqtt.register_callback(route_data)

    print("--- Replay Started ---")
    
    # 1. Send env data
    print("Injecting ENV...")
    mqtt.process_message("esp32/device/office/state", json.dumps({
        "temperature": 27.5, "humidity": 50, "co2": 450
    }))
    
    # 2. Send occ data (PIR)
    print("Injecting OCC (PIR)...")
    mqtt.process_message("esp32/device/office/state", json.dumps({
        "motion": 1
    }))
    
    # 3. Evaluate
    features = fe.compute_features()
    state, probs, reasons = hmm.update(features)
    decision = ctrl.decide(features, state, {"empty": probs[0], "transition": probs[1], "occupied": probs[2]})
    
    print(f"HMM State: {state}, Prob: {probs}")
    print(f"Decision: {decision['proposed_action']}, Executed: {decision['executed']}")
    print(f"Reasons: {decision['reason_codes']}")
    
    print("--- Replay Finished ---")

if __name__ == "__main__":
    run_replay()
