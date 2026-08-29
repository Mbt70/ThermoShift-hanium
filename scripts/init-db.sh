#!/usr/bin/env bash
# =====================================================================
# init-db.sh — 스키마를 적용하고 구 SQLite 실측 데이터를 이관한다.
#
#   bash scripts/init-db.sh            # 비어 있을 때만 채운다
#   bash scripts/init-db.sh --reset    # 표를 비우고 처음부터 다시
#
# sudo 가 필요 없다. scripts/bootstrap-pi.sh 를 먼저 돌려서 PostgreSQL 과
# /etc/thermoshift.env 가 준비돼 있어야 한다.
# =====================================================================
# pipefail 은 쓰지 않는다. `... | grep -q` 나 `| head` 처럼 뒤쪽이 파이프를
# 일찍 닫는 검사에서 앞쪽 명령이 SIGPIPE 로 죽고, 그게 조건 실패로 둔갑한다.
# (실제로 bootstrap-pi.sh 에서 구 백엔드 정지가 통째로 건너뛰어졌다.)
set -uo pipefail
set +o pipefail
set -e

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PY="$REPO/.venv/bin/python"
cd "$REPO"

# 부트스트랩이 만든 DB 비밀번호를 읽는다.
if [ -r /etc/thermoshift.env ]; then
  set -a; . /etc/thermoshift.env; set +a
fi
export PGHOST="${DB_HOST:-localhost}" PGPORT="${DB_PORT:-5432}"
export PGUSER="${DB_USER:-thermoshift}" PGDATABASE="${DB_NAME:-thermoshift}"
export PGPASSWORD="${DB_PASSWORD:-thermoshift1234}"

say() { printf '\n\033[1;36m== %s\033[0m\n' "$*"; }

command -v psql >/dev/null || {
  echo "psql 이 없습니다. 먼저:  sudo bash scripts/bootstrap-pi.sh" >&2; exit 1; }
[ -x "$PY" ] || { echo "venv 가 없습니다: $PY" >&2; exit 1; }

say "접속 확인"
psql -tAc "SELECT version()" | head -1

RESET=""
[ "${1:-}" = "--reset" ] && RESET="--reset"

# 스키마는 001~004 가 단일 원본이다. 이미 적용돼 있으면(users 표 존재)
# 다시 돌리지 않는다 — 002 는 CREATE TABLE 이라 두 번 돌면 실패한다.
if psql -tAc "SELECT to_regclass('public.users')" | grep -q users; then
  say "스키마 이미 적용됨 — 넘어감"
else
  # db/seed.sql 은 일부러 넣지 않는다. 개발용 더미(공학관 401호 등)라서
  # 이관해 온 실측 기록과 섞이면 어느 쪽이 진짜인지 화면에서 구분되지
  # 않는다. 빈 화면을 보고 싶을 때만 손으로 적용한다:  psql -f db/seed.sql
  say "스키마 적용 (001 → 004)"
  for f in db/001_types.sql db/002_tables.sql db/003_indexs.sql db/004_gateway.sql; do
    echo "   $f"
    psql -v ON_ERROR_STOP=1 -q -f "$f"
  done
fi

say "구 SQLite 실측 데이터 이관"
"$PY" db/migrate_sqlite_to_pg.py $RESET

say "결과 확인"
psql -c "
SELECT 'users' t, count(*) FROM users
UNION ALL SELECT 'rooms',               count(*) FROM rooms
UNION ALL SELECT 'devices',             count(*) FROM devices
UNION ALL SELECT 'schedules',           count(*) FROM schedules
UNION ALL SELECT 'sensor_env',          count(*) FROM sensor_env
UNION ALL SELECT 'sensor_pir',          count(*) FROM sensor_pir
UNION ALL SELECT 'sensor_door',         count(*) FROM sensor_door
UNION ALL SELECT 'occupancy_estimates', count(*) FROM occupancy_estimates
UNION ALL SELECT 'control_decisions',   count(*) FROM control_decisions
UNION ALL SELECT 'hvac_commands',       count(*) FROM hvac_commands
UNION ALL SELECT 'ir_events',           count(*) FROM ir_events
UNION ALL SELECT 'event_logs',          count(*) FROM event_logs
UNION ALL SELECT 'operation_sessions',  count(*) FROM operation_sessions
ORDER BY 1;"
