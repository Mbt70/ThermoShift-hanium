#!/bin/bash
# 펠티어(냉각 릴레이)를 천천히 껐다 켜며 배선/펌웨어를 진단한다.
#
#   bash infra/mqtt/relay-toggle.sh          # 10초 주기로 10회
#   bash infra/mqtt/relay-toggle.sh 5 20     # 5초 주기로 20회
#
# 토글하는 동안 멀티미터로 확인할 것
#   1. ESP32 의 릴레이 제어 GPIO 핀 ↔ GND : 전압이 0V ↔ 3.3V 로 바뀌는가
#        바뀐다  → 펌웨어는 정상. 릴레이 모듈 배선/전원을 점검
#        안 바뀐다 → 펌웨어가 GPIO 를 구동하지 않음. 펌웨어 수정 필요
#   2. 릴레이 모듈 VCC ↔ GND : 5V(또는 3.3V)가 들어오는가
#   3. 릴레이 출력 접점 도통 : ON 일 때 도통되는가
#
# 주의: cooling/cmd 만 쓴다. esp32/device/ir_01/control 은 IR 프로파일이
#       설정돼 있지 않으면 릴레이를 OFF 로 되돌리므로 진단 중에는 쓰지 않는다.
set -euo pipefail

INTERVAL="${1:-10}"
CYCLES="${2:-10}"
HOST="${MQTT_HOST:-localhost}"
CMD_TOPIC="thermoshift/ir_01/cooling/cmd"
STATE_TOPIC="thermoshift/ir_01/cooling/state"

cleanup() {
  echo
  echo "정리: 릴레이를 OFF 로 되돌립니다"
  mosquitto_pub -h "$HOST" -t "$CMD_TOPIC" -m 'OFF' || true
}
trap cleanup EXIT INT TERM

echo "펠티어 릴레이 토글 진단 — ${INTERVAL}초 주기, ${CYCLES}회"
echo "  명령 토픽: $CMD_TOPIC"
echo

for i in $(seq 1 "$CYCLES"); do
  for state in ON OFF; do
    mosquitto_pub -h "$HOST" -t "$CMD_TOPIC" -m "$state"
    sleep 2
    reported="$(mosquitto_sub -h "$HOST" -t "$STATE_TOPIC" -C 1 -W 3 2>/dev/null || echo '무응답')"
    printf "  [%2d/%d] 보냄=%-3s  노드회신=%-3s  %s\n" \
      "$i" "$CYCLES" "$state" "$reported" "$(date +%H:%M:%S)"
    sleep "$INTERVAL"
  done
done
