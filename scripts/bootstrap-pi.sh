#!/usr/bin/env bash
# =====================================================================
# bootstrap-pi.sh — 라즈베리파이를 ThermoShift 운영 상태로 만든다.
#
#   sudo bash scripts/bootstrap-pi.sh
#
# 이 스크립트가 하는 일 (모두 멱등 — 여러 번 돌려도 안전):
#   1. 구 저장소 백엔드(:8000, InfluxDB) 정지·비활성화
#      → 새 api 가 같은 포트를 쓰고, MQTT client_id 도 충돌한다.
#   2. PostgreSQL 17 설치 + thermoshift 롤·DB 생성
#   3. /etc/thermoshift.env 생성 (DB 비밀번호 보관, 저장소에 두지 않음)
#
# 스키마 적용과 데이터 이관은 sudo 가 필요 없으므로 별도다:
#   bash scripts/init-db.sh
# =====================================================================
# pipefail 은 쓰지 않는다. `... | grep -q` 처럼 뒤쪽이 파이프를 일찍 닫는
# 검사에서 앞쪽 명령이 SIGPIPE 로 죽고, 그게 조건 실패로 둔갑한다.
set -uo pipefail
set +o pipefail
set -e

if [ "$(id -u)" -ne 0 ]; then
  echo "sudo 로 실행하세요:  sudo bash scripts/bootstrap-pi.sh" >&2
  exit 1
fi

APP_USER="${SUDO_USER:-thermo}"
DB_NAME="thermoshift"
DB_USER="thermoshift"
ENV_FILE="/etc/thermoshift.env"

say() { printf '\n\033[1;36m== %s\033[0m\n' "$*"; }

# ---------------------------------------------------------------------
say "1/4  구 저장소 백엔드 정리"
# ~/thermoshift/backend 는 InfluxDB 기반 구 버전이다. 새 api 와 포트(8000)가
# 겹치고, 둘 다 MQTT 를 구독하면 제어 명령이 충돌한다(docs/decision-log.md).
if systemctl list-unit-files --no-pager --no-legend \
     | grep -q '^thermoshift-backend\.service'; then
  systemctl disable --now thermoshift-backend.service 2>/dev/null || true
  echo "   thermoshift-backend.service 정지·비활성화됨"
else
  echo "   thermoshift-backend.service 없음 — 넘어감"
fi

# ---------------------------------------------------------------------
say "2/4  PostgreSQL 설치"
if command -v psql >/dev/null 2>&1; then
  echo "   이미 설치됨: $(psql --version)"
else
  export DEBIAN_FRONTEND=noninteractive
  apt-get update -qq
  apt-get install -y postgresql postgresql-contrib
  echo "   설치 완료: $(psql --version)"
fi
systemctl enable --now postgresql

# 소켓이 열릴 때까지 잠깐 기다린다 (설치 직후 초기화에 몇 초 걸린다).
for _ in $(seq 1 30); do
  su - postgres -c 'psql -tAc "SELECT 1"' >/dev/null 2>&1 && break
  sleep 1
done

# ---------------------------------------------------------------------
say "3/4  롤·데이터베이스 생성"
# 비밀번호는 매번 새로 만들지 않는다. 이미 env 파일이 있으면 그 값을 쓴다
# (재실행 시 비밀번호가 바뀌면 돌고 있는 서비스가 전부 끊긴다).
if [ -f "$ENV_FILE" ] && grep -q '^DB_PASSWORD=' "$ENV_FILE"; then
  DB_PASSWORD="$(grep '^DB_PASSWORD=' "$ENV_FILE" | head -1 | cut -d= -f2-)"
  echo "   기존 비밀번호를 $ENV_FILE 에서 재사용"
else
  DB_PASSWORD="$(head -c 24 /dev/urandom | base64 | tr -d '/+=' | head -c 24)"
  echo "   새 비밀번호 생성"
fi

su - postgres -c "psql -v ON_ERROR_STOP=1" <<SQL
DO \$\$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '${DB_USER}') THEN
    CREATE ROLE ${DB_USER} LOGIN;
  END IF;
END
\$\$;
ALTER ROLE ${DB_USER} WITH PASSWORD '${DB_PASSWORD}';
SQL

if ! su - postgres -c "psql -tAc \"SELECT 1 FROM pg_database WHERE datname='${DB_NAME}'\"" | grep -q 1; then
  su - postgres -c "createdb -O ${DB_USER} ${DB_NAME}"
  echo "   데이터베이스 ${DB_NAME} 생성됨"
else
  echo "   데이터베이스 ${DB_NAME} 이미 있음"
fi

# ---------------------------------------------------------------------
say "4/4  $ENV_FILE 기록"
# systemd 유닛들이 EnvironmentFile 로 읽는다. ANTHROPIC_API_KEY 를 넣으면
# api 의 AI 해설 기능이 켜진다 (키는 반드시 서버에만 둔다).
KEEP_KEY=""
if [ -f "$ENV_FILE" ] && grep -q '^ANTHROPIC_API_KEY=' "$ENV_FILE"; then
  KEEP_KEY="$(grep '^ANTHROPIC_API_KEY=' "$ENV_FILE" | head -1)"
fi

install -o "$APP_USER" -g "$APP_USER" -m 600 /dev/null "$ENV_FILE"
{
  echo "DB_HOST=localhost"
  echo "DB_PORT=5432"
  echo "DB_USER=${DB_USER}"
  echo "DB_NAME=${DB_NAME}"
  echo "DB_PASSWORD=${DB_PASSWORD}"
  [ -n "$KEEP_KEY" ] && echo "$KEEP_KEY"
} > "$ENV_FILE"
chown "$APP_USER:$APP_USER" "$ENV_FILE"
chmod 600 "$ENV_FILE"

echo
echo "완료. 다음 단계 (sudo 없이):"
echo "    cd ~/ThermoShift-hanium && bash scripts/init-db.sh"
