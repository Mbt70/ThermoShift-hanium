#!/usr/bin/env python3
"""ThermoShift 합성 패킷 UI 리허설 도구.

이 스크립트의 값은 센서 실측이 아니며 공모전 성과 자료로 사용할 수 없다.
실센서 ID와 섞이지 않도록 ``demo_*`` ID로만 발행한다.

사용법:
  1. PC나 태블릿에서 https://thermoshift.tail46fe5e.ts.net 대시보드를 켭니다.
  2. 화면 녹화(OBS, 윈도우 Win+G, 맥 Cmd+Shift+5)를 시작합니다.
  3. 터미널에서 이 스크립트를 실행합니다:
       python scripts/record_demo.py
  4. 터미널에 초 단위로 표시되는 [나레이션 가이드]에 맞춰 설명하시면
     대시보드가 5초마다 실시간으로 반응하여 최고의 시연 영상이 완성됩니다!
"""

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import paho.mqtt.client as mqtt

_REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--allow-synthetic",
        action="store_true",
        help="합성 패킷임을 이해하고 demo_* 장치 ID로 발행",
    )
    args = parser.parse_args()
    if not args.allow_synthetic:
        parser.error(
            "합성 데이터의 DB 유입을 막기 위해 기본 실행은 차단됩니다. "
            "UI 리허설에만 --allow-synthetic를 사용하세요."
        )

    print("=" * 70)
    print("🎬 ThermoShift 시연 영상 촬영 자동 진행기 (3분 완성 코스)")
    print("=" * 70)
    print("브라우저에서 https://thermoshift.tail46fe5e.ts.net 대시보드를 띄우고")
    print("화면 녹화를 시작한 뒤 Enter를 누르세요...")
    input()

    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="video_demo_runner")
    client.connect("localhost", 1883, 60)
    client.loop_start()

    def send_packet(temp, hum, co2, pir, door, desc):
        now = datetime.now(timezone.utc).isoformat()
        client.publish("thermoshift/demo_occ_01/data", json.dumps({
            "node": "demo_occ_01", "timestamp": now, "pir": pir, "door": door,
            "door_event": False, "source": "synthetic_demo"
        }))
        client.publish("thermoshift/demo_env_01/data", json.dumps({
            "node": "demo_env_01", "timestamp": now, "temperature": temp,
            "humidity": hum, "co2": co2, "source": "synthetic_demo"
        }))
        print(f"📡 [패킷 전송] {desc} (T={temp}℃, RH={hum}%, CO2={co2}ppm, PIR={pir})")

    # -------------------------------------------------------------
    # 1단계 (0:00 ~ 0:25): 평온한 실내 환경 (대시보드 소개)
    # -------------------------------------------------------------
    print("\n" + "#" * 60)
    print("▶ [1단계: 0~25초] 평온한 실내 환경 및 대시보드 소개")
    print("🎤 [나레이션 멘트]:")
    print('  "안녕하세요, AI 기반 스마트 빌딩 공조 최적화 솔루션 ThermoShift입니다.')
    print('   지금 보시는 화면은 실시간 3D 디지털 트윈으로, 현재 공간의 온습도와')
    print('   ISO 7730 국제표준 PMV 쾌적도 지수가 실시간으로 모니터링되고 있습니다."')
    print("#" * 60)
    send_packet(24.2, 48.0, 480, False, "closed", "평온한 공실 상태")
    time.sleep(20)

    # -------------------------------------------------------------
    # 2단계 (0:25 ~ 0:55): 재실자 2명 입장 & 체온/호흡 급증
    # -------------------------------------------------------------
    print("\n" + "#" * 60)
    print("▶ [2단계: 25~55초] 재실자 2명 입장 & 물리-통계 융합 재실 추정")
    print("🎤 [나레이션 멘트]:")
    print('  "이제 재실자가 공간에 입장합니다. 문이 열리고 사람이 들어오면 CO2 농도가 급증합니다.')
    print('   저희는 CO2 질량수지와 PIR을 확률적으로 결합해 PIR 단독의 정적 재실 사각지대를 보완하고,')
    print('   제어에 필요한 재실 상태와 내부 발열 외란의 근사치를 추정합니다."')
    print("#" * 60)
    send_packet(26.8, 68.0, 920, True, "closed", "재실자 입장 시작")
    time.sleep(15)
    send_packet(27.8, 72.0, 1080, True, "closed", "온열 부하 및 CO2 급증")
    time.sleep(15)

    # -------------------------------------------------------------
    # 3단계 (0:55 ~ 1:30): MPC 선제 냉방 트리거 & 쾌적 회복
    # -------------------------------------------------------------
    print("\n" + "#" * 60)
    print("▶ [3단계: 55~90초] 쾌적 대역 기반 냉방 제어")
    print("🎤 [나레이션 멘트]:")
    print('  "온열감이 쾌적 허용대역을 벗어나면 안전 규칙 제어가 냉방을 요청합니다.')
    print('   RC 열모델 교정과 비교 실험이 끝난 뒤에는 같은 제어 경로에 Economic MPC를 적용해')
    print('   쾌적 위반, 소비전력, 제어 변동을 함께 최소화할 계획입니다."')
    print("#" * 60)
    send_packet(26.5, 62.0, 950, True, "closed", "급속 냉각 진행 중")
    time.sleep(15)
    send_packet(25.0, 52.0, 820, True, "closed", "쾌적 온도 도달")
    time.sleep(15)

    # -------------------------------------------------------------
    # 4단계 (1:30 ~ 2:05): Setback 절전 모드 자동 전환
    # -------------------------------------------------------------
    print("\n" + "#" * 60)
    print("▶ [4단계: 90~125초] 쾌적 대역 진입 후 과냉각 방지")
    print("🎤 [나레이션 멘트]:")
    print('  "실내가 쾌적 대역에 도달하면, 불필요한 과냉각을 차단하고 설정 온도를 25.5도로')
    print('   자연스럽게 완화하는 Setback 절전 모드로 자동 전환됩니다.')
    print('   현재는 이 제어 동작과 전력값을 함께 기록하며, 동일 외란의 기준 제어와 비교한 뒤')
    print('   절감률과 쾌적 대역 유지율을 결과로 제시합니다."')
    print("#" * 60)
    send_packet(24.5, 48.0, 680, True, "closed", "Setback 절전 유지")
    time.sleep(25)

    # -------------------------------------------------------------
    # 5단계 (2:05 ~ 2:30): 제어 아키텍처 확장 계획
    # -------------------------------------------------------------
    print("\n" + "#" * 60)
    print("▶ [5단계: 125~150초] 12L 목업 → 실제 공간 확장 전략")
    print("🎤 [나레이션 멘트]:")
    print('  "마지막으로 [공간 스케일링] 탭입니다. 목업에서는 센서·추정·제어의 폐루프 구조를 검증하고,')
    print('   실제 공간에서는 같은 RC·MPC 구조를 사용하되 R, C, 환기량과 장치 효율을 현장 데이터로 다시 식별합니다.')
    print('   이상으로 ThermoShift 시연을 마칩니다. 감사합니다!"')
    print("#" * 60)
    time.sleep(20)

    client.loop_stop()
    client.disconnect()
    print("\n🎉 [촬영 완료] 축하합니다! 훌륭한 시연 영상이 완성되었습니다!")


if __name__ == "__main__":
    main()
