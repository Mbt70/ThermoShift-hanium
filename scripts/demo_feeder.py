#!/usr/bin/env python3
"""ThermoShift 실시간 시연 시나리오 피더 (Live Demo Feeder).

시연 목적:
- 심사위원 앞에서 하드웨어(ESP32) 연결 전이거나 네트워크 흔들림이 있어도
  시스템이 어떻게 재실자를 감지하고, PMV 쾌적도와 전력을 최적화하는지
  드라마틱하고 직관적으로 시연합니다.
- 실제 ESP32 센서가 켜지면 실측 패킷이 덮어쓰므로 100% 안전합니다.

시나리오 옵션:
1. occupancy_spike : 사람이 방에 들어와 체온/CO2가 상승하는 시나리오 (MPC 냉방 트리거)
2. comfortable_setback : 쾌적 밴드 도달 후 에너지를 아끼기 위해 Setback 완화하는 시나리오
3. empty_turnoff : 공실 감지 후 즉시 불필요한 냉방을 끄는 시나리오 (에너지 절감)
4. co2_alert : CO2가 1,500ppm을 초과하여 환기 경보가 발생하는 시나리오
"""

import argparse
import json
import time
from datetime import datetime, timezone
import paho.mqtt.client as mqtt
from paho.mqtt.enums import CallbackAPIVersion

def main():
    parser = argparse.ArgumentParser(description="ThermoShift Demo Feeder")
    parser.add_argument("--scenario", choices=["occupancy", "setback", "empty", "co2", "loop"], default="occupancy")
    parser.add_argument("--host", default="localhost")
    parser.add_argument("--port", type=int, default=1883)
    args = parser.parse_args()

    client = mqtt.Client(callback_api_version=CallbackAPIVersion.VERSION2, client_id="demo_feeder")
    client.connect(args.host, args.port, 60)
    client.loop_start()

    print(f"🎬 ThermoShift 시연 피더 시작 (시나리오: {args.scenario})")

    def send_env(temp, hum, co2):
        now = datetime.now(timezone.utc).isoformat()
        payload = {
            "device_id": "env_01",
            "timestamp": now,
            "temperature": temp, "temp_c": temp,
            "humidity_rh": hum,
            "co2_ppm": co2
        }
        client.publish("thermoshift/env_01", json.dumps(payload))
        print(f"  [ENV] 온도 {temp:.1f}℃, 습도 {hum:.0f}%, CO2 {co2}ppm 전송")

    def send_occ(pir, door_state, door_event):
        now = datetime.now(timezone.utc).isoformat()
        payload = {
            "device_id": "occ_01",
            "timestamp": now,
            "pir": pir,
            "door": door_state,
            "door_event": door_event
        }
        client.publish("thermoshift/occ_01", json.dumps(payload))
        print(f"  [OCC] PIR={'감지' if pir else '없음'}, 문={door_state} 전송")

    if args.scenario == "occupancy":
        print("\n▶ 시나리오 1: 재실자 입장 & 온열 부하 증가 (MPC 냉방 가동 유도)")
        send_occ(pir=True, door_state="closed", door_event=True)
        send_env(temp=27.2, hum=72.0, co2=950)
        time.sleep(2)
        send_occ(pir=True, door_state="closed", door_event=False)
        send_env(temp=27.4, hum=73.0, co2=1050)

    elif args.scenario == "setback":
        print("\n▶ 시나리오 2: 쾌적 범위 도달 & Setback 에너지 절감 최적화")
        send_occ(pir=True, door_state="closed", door_event=False)
        send_env(temp=24.6, hum=48.0, co2=650)

    elif args.scenario == "empty":
        print("\n▶ 시나리오 3: 퇴실 & 공실 감지 (냉방 차단으로 전력 낭비 방지)")
        send_occ(pir=False, door_state="closed", door_event=True)
        send_env(temp=25.0, hum=50.0, co2=500)

    elif args.scenario == "co2":
        print("\n▶ 시나리오 4: CO2 급증 & 즉시 환기 경보")
        send_occ(pir=True, door_state="closed", door_event=False)
        send_env(temp=25.5, hum=60.0, co2=1650)

    elif args.scenario == "loop":
        print("\n▶ 시나리오 루프 실행 (10초 간격으로 실시간 센서 패킷 주입)")
        temps = [26.8, 27.2, 26.5, 25.8, 25.2, 24.8, 24.5]
        try:
            for t in temps:
                send_occ(pir=True, door_state="closed", door_event=False)
                send_env(temp=t, hum=65.0, co2=820)
                time.sleep(10)
        except KeyboardInterrupt:
            pass

    time.sleep(1)
    client.loop_stop()
    client.disconnect()
    print("✅ 시연 패킷 전송 완료.")

if __name__ == "__main__":
    main()
