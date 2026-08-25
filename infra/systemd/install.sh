#!/bin/bash
# ThermoShift 서비스를 systemd에 등록한다. 재부팅해도 살아난다.
#
#   bash infra/systemd/install.sh
#
# 구 시스템(thermoshift-backend, thermoshift-edge)이 돌고 있으면 먼저 멈춘다.
# 같은 MQTT 토픽을 두 프로세스가 구독하면 제어 명령이 중복 발생하고,
# 서로 다른 DB에 데이터가 갈라져 쌓인다.
set -e

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DB_PATH="${THERMOSHIFT_DB:-/home/thermo/thermoshift-data/thermoshift.db}"
OLD_EDGE_DB="/home/thermo/thermoshift-edge/thermoshift_edge.db"

echo "1) 구 시스템 정지"
for unit in thermoshift-backend thermoshift-edge; do
  if systemctl is-enabled "$unit" >/dev/null 2>&1; then
    sudo systemctl disable --now "$unit" || true
    echo "   $unit 정지·해제"
  fi
done
# systemd 밖에서 수동 실행된 구 edge 도 정리한다.
if pkill -f 'thermoshift-edge/venv/bin/python -m app.main' 2>/dev/null; then
  echo "   수동 실행된 구 edge 정지"
fi

echo "2) DB 마이그레이션"
python3 "$REPO/db/migrate.py"

if [ -f "$OLD_EDGE_DB" ]; then
  ROOM_ID="$(sqlite3 "$DB_PATH" "select id from rooms limit 1" 2>/dev/null || true)"
  if [ -n "$ROOM_ID" ]; then
    echo "3) 구 DB에 남은 데이터 병합"
    python3 "$REPO/db/migrate.py" --merge-from "$OLD_EDGE_DB" --merge-room "$ROOM_ID"
  else
    echo "3) 공간이 아직 등록되지 않아 병합을 건너뜁니다"
    echo "   나중에: python3 db/migrate.py --merge-from $OLD_EDGE_DB --merge-room <공간ID>"
  fi
fi

echo "4) 게이트웨이 설정 확인"
if [ ! -f "$REPO/gateway/config/config.yaml" ]; then
  cp "$REPO/gateway/config/config.example.yaml" "$REPO/gateway/config/config.yaml"
  echo "   config.yaml 생성 (shadow 모드)"
fi

echo "5) 서비스 등록"
sudo cp "$REPO"/infra/systemd/thermoshift-{gateway,api,web}.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now thermoshift-gateway thermoshift-api thermoshift-web

echo
echo "완료. 상태 확인:"
echo "  systemctl status thermoshift-gateway thermoshift-api thermoshift-web"
echo "  curl http://localhost:8100/api/health"
echo "  대시보드: http://$(hostname -I | awk '{print $1}'):8501"
echo
echo "외부 공개는 별도입니다:"
echo "  bash infra/cloudflared/quick-tunnel.sh   # 임시 주소 (계정 불필요)"
echo "  docs/deployment.md                        # 고정 주소 (Named Tunnel)"
