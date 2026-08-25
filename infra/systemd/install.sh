#!/bin/bash
# ThermoShift 서비스를 systemd 에 등록한다. 재부팅해도 살아난다.
#
#   bash infra/systemd/install.sh
#
# 전제: PostgreSQL 이 떠 있고 db/001~004 가 적용돼 있어야 한다.
#   docker compose -f infra/docker-compose.yml up -d   # 컨테이너로 띄우는 경우
# 컨테이너는 db/ 를 initdb 디렉터리로 마운트하므로 최초 기동 때 스키마가
# 자동 적용된다. 네이티브 설치라면 psql 로 직접 넣어야 한다.
set -e

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
ENV_FILE="/etc/thermoshift.env"

export DB_HOST="${DB_HOST:-localhost}"
export DB_PORT="${DB_PORT:-5432}"
export DB_USER="${DB_USER:-thermoshift}"
export DB_NAME="${DB_NAME:-thermoshift}"

echo "1) 구 시스템 정지"
# 통합 전 저장소들이 같은 MQTT 토픽을 구독하면 제어 명령이 중복 발생하고,
# 서로 다른 DB 에 데이터가 갈라져 쌓인다.
for unit in thermoshift-backend thermoshift-edge; do
  if systemctl is-enabled "$unit" >/dev/null 2>&1; then
    sudo systemctl disable --now "$unit" || true
    echo "   $unit 정지·해제"
  fi
done
if pkill -f 'thermoshift-edge/venv/bin/python -m app.main' 2>/dev/null; then
  echo "   수동 실행된 구 edge 정지"
fi

echo "2) PostgreSQL 연결 확인"
if ! python3 - <<'PY'
import os, sys
try:
    import psycopg
except ImportError:
    sys.exit("   psycopg 가 없습니다. pip install -r requirements.txt 를 먼저 하세요.")
try:
    psycopg.connect(
        host=os.environ["DB_HOST"], port=os.environ["DB_PORT"],
        user=os.environ["DB_USER"], dbname=os.environ["DB_NAME"],
        password=os.environ.get("DB_PASSWORD", "thermoshift1234"),
        connect_timeout=5,
    ).close()
except Exception as exc:
    sys.exit(f"   접속 실패: {exc}")
PY
then
  echo
  echo "   PostgreSQL 이 떠 있지 않거나 스키마가 없습니다."
  echo "   docker compose -f infra/docker-compose.yml up -d"
  exit 1
fi
echo "   OK"

echo "3) 게이트웨이 설정 확인"
if [ ! -f "$REPO/gateway/config/config.yaml" ]; then
  cp "$REPO/gateway/config/config.example.yaml" "$REPO/gateway/config/config.yaml"
  echo "   config.yaml 생성 (shadow 모드)"
fi

echo "4) 비밀 설정 파일"
if [ ! -f "$ENV_FILE" ]; then
  sudo install -o thermo -g thermo -m 600 /dev/null "$ENV_FILE"
  echo "DB_PASSWORD=thermoshift1234" | sudo tee "$ENV_FILE" >/dev/null
  echo "   $ENV_FILE 생성 — 비밀번호와 ANTHROPIC_API_KEY 를 여기에 넣으세요"
fi

echo "5) 서비스 등록"
sudo cp "$REPO"/infra/systemd/thermoshift-{gateway,api,web}.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now thermoshift-gateway thermoshift-api thermoshift-web

echo
echo "완료. 상태 확인:"
echo "  systemctl status thermoshift-gateway thermoshift-api thermoshift-web"
echo "  curl http://localhost:8000/health"
echo "  대시보드: http://$(hostname -I | awk '{print $1}'):8501"
echo
echo "외부 공개는 별도입니다:"
echo "  bash infra/cloudflared/quick-tunnel.sh   # 임시 주소 (계정 불필요)"
echo "  docs/deployment.md                        # 고정 주소 (Named Tunnel)"
