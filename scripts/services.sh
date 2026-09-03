#!/usr/bin/env bash
# =====================================================================
# services.sh — ThermoShift 서비스를 사용자 systemd 로 관리한다.
#
#   bash scripts/services.sh install   # 유닛 설치 + 구 서비스 정리
#   bash scripts/services.sh up        # api·web 시작 (gateway 는 별도)
#   bash scripts/services.sh gateway   # 제어 게이트웨이까지 시작
#   bash scripts/services.sh down      # 전부 정지
#   bash scripts/services.sh status
#   bash scripts/services.sh logs [api|web|gateway]
#
# 왜 사용자(systemd --user) 레벨인가
# ---------------------------------
# infra/systemd/ 의 유닛은 시스템 레벨이라 설치에 sudo 가 필요하다. 이
# 파이는 이미 linger 가 켜져 있어(Linger=yes) 사용자 유닛도 부팅 때 뜨고,
# 터널도 그렇게 돌고 있었다. sudo 없이 같은 결과를 얻을 수 있으므로
# 사용자 레벨로 통일한다. 여러 대에 배포할 때는 시스템 레벨이 낫다.
# =====================================================================
# pipefail 은 쓰지 않는다. `... | grep -q` 나 `| head` 처럼 뒤쪽이 파이프를
# 일찍 닫는 검사에서 앞쪽 명령이 SIGPIPE 로 죽고, 그게 조건 실패로 둔갑한다.
# (실제로 bootstrap-pi.sh 에서 구 백엔드 정지가 통째로 건너뛰어졌다.)
set -uo pipefail
set +o pipefail
set -e

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
UNIT_DIR="$HOME/.config/systemd/user"
PY="$REPO/.venv/bin/python"
SERVICES=(thermoshift-api thermoshift-web thermoshift-gateway)

# 구 저장소에서 돌던 것들. 새 스택과 포트·MQTT 를 놓고 부딪힌다.
LEGACY_USER=(thermoshift-edge thermoshift-tunnel-api thermoshift-tunnel-web)

say() { printf '\n\033[1;36m== %s\033[0m\n' "$*"; }

install_units() {
  mkdir -p "$UNIT_DIR"

  cat > "$UNIT_DIR/thermoshift-api.service" <<EOF
[Unit]
Description=ThermoShift API (FastAPI :8000)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory=$REPO
# DB 비밀번호는 저장소에 두지 않는다. bootstrap-pi.sh 가 만든 파일을 읽는다.
EnvironmentFile=-/etc/thermoshift.env
# 사용자 유닛은 시스템 유닛(postgresql)에 After= 로 걸 수 없다. 부팅 때
# PostgreSQL 이 아직 소켓을 열기 전에 API 가 뜨면 첫 요청들이 전부 실패한다.
# 그래서 여기서 직접 기다린다. 60초 안에 안 열리면 그대로 시작하고,
# 커넥션 풀이 뒤늦게라도 붙는다 (Restart=always 가 받쳐 준다).
ExecStartPre=$REPO/scripts/wait-for.sh 127.0.0.1 5432 60
ExecStart=$PY -m uvicorn api.main:app --host 127.0.0.1 --port 8000
Restart=always
RestartSec=5

[Install]
WantedBy=default.target
EOF

  cat > "$UNIT_DIR/thermoshift-web.service" <<EOF
[Unit]
Description=ThermoShift Web (Streamlit 대시보드 :8501)
After=network.target thermoshift-api.service

[Service]
Type=simple
WorkingDirectory=$REPO
Environment=THERMOSHIFT_API_URL=http://127.0.0.1:8000
EnvironmentFile=-/etc/thermoshift.env
ExecStartPre=$REPO/scripts/wait-for.sh 127.0.0.1 8000 60
ExecStart=$PY -m streamlit run web/main.py \\
  --server.port 8501 --server.address 127.0.0.1 \\
  --server.headless true --browser.gatherUsageStats false
Restart=always
RestartSec=5

[Install]
WantedBy=default.target
EOF

  cat > "$UNIT_DIR/thermoshift-gateway.service" <<EOF
[Unit]
Description=ThermoShift Gateway (MQTT 수집 · 재실 추정 · HVAC 제어)
After=network.target mosquitto.service

[Service]
Type=simple
WorkingDirectory=$REPO/gateway
EnvironmentFile=-/etc/thermoshift.env
ExecStart=$PY -m app.main
Restart=on-failure
RestartSec=10

[Install]
WantedBy=default.target
EOF

  systemctl --user daemon-reload
  echo "  유닛 3개 설치됨: $UNIT_DIR"
}

stop_legacy() {
  # 구 서비스를 끄지 않으면 포트(8000)와 MQTT 구독이 겹친다. 두 제어기가
  # 동시에 돌면 한쪽은 냉방을 켜고 다른 쪽은 끈다 (docs/decision-log.md).
  for u in "${LEGACY_USER[@]}"; do
    if systemctl --user list-unit-files | grep -q "^${u}\.service"; then
      systemctl --user disable --now "$u" 2>/dev/null || true
      echo "  정지·비활성화: $u (사용자)"
    fi
  done
  if systemctl is-enabled thermoshift-backend >/dev/null 2>&1 \
     || systemctl is-active thermoshift-backend >/dev/null 2>&1; then
    echo
    echo "  ! 시스템 서비스 thermoshift-backend 가 아직 살아 있습니다 (구 InfluxDB 백엔드, :8000)."
    echo "    새 API 와 포트가 겹칩니다. sudo 로 꺼 주세요:"
    echo "        sudo systemctl disable --now thermoshift-backend"
  fi
}

case "${1:-status}" in
  install)
    say "유닛 설치"; install_units
    say "구 서비스 정리"; stop_legacy
    ;;
  up)
    [ -f "$UNIT_DIR/thermoshift-api.service" ] || install_units
    say "api · web 시작"
    systemctl --user enable --now thermoshift-api thermoshift-web
    sleep 3
    "$0" status
    ;;
  gateway)
    say "gateway 시작"
    systemctl --user enable --now thermoshift-gateway
    sleep 2
    systemctl --user status thermoshift-gateway --no-pager | grep -E "Active:|Main PID:"
    ;;
  down)
    say "정지"
    systemctl --user disable --now "${SERVICES[@]}" 2>/dev/null || true
    ;;
  status)
    say "서비스"
    for u in "${SERVICES[@]}"; do
      state="$(systemctl --user is-active "$u" 2>/dev/null || true)"
      printf "  %-28s %s\n" "$u" "${state:-없음}"
    done
    say "포트"
    for p in 8000 8501 1883 5432; do
      if (exec 3<>/dev/tcp/127.0.0.1/$p) 2>/dev/null; then
        printf "  127.0.0.1:%-6s 열림\n" "$p"
      else
        printf "  127.0.0.1:%-6s 닫힘\n" "$p"
      fi
    done
    say "API 헬스체크"
    curl -s --max-time 5 http://127.0.0.1:8000/health || echo "  응답 없음"
    echo
    ;;
  logs)
    journalctl --user -u "thermoshift-${2:-api}" -f
    ;;
  *)
    sed -n '3,12p' "$0"; exit 1
    ;;
esac
