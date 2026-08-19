#!/bin/bash
# ThermoShift 서비스 3종을 systemd에 등록한다.
#
# 주의: 구 thermoshift-backend / thermoshift-edge 가 돌고 있다면 먼저 멈춰야 한다.
#       같은 MQTT 토픽을 두 프로세스가 구독하면 제어 명령이 중복 발생한다.
set -e

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

echo "1) DB 마이그레이션"
python3 "$REPO/db/migrate.py"

echo "2) 서비스 파일 복사"
sudo cp "$REPO"/infra/systemd/thermoshift-{gateway,api,web}.service /etc/systemd/system/
sudo systemctl daemon-reload

echo "3) 기동"
sudo systemctl enable --now thermoshift-gateway thermoshift-api thermoshift-web

echo
echo "완료. 상태 확인:"
echo "  systemctl status thermoshift-gateway thermoshift-api thermoshift-web"
echo "  curl http://localhost:8100/api/health"
echo "  대시보드: http://<라즈베리파이 IP>:8501"
