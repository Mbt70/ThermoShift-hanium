#!/usr/bin/env bash
# =====================================================================
# setup-funnel.sh — 고정 공개 주소를 만든다 (Tailscale Funnel).
#
#   bash scripts/setup-funnel.sh
#
# 왜 Cloudflare Quick Tunnel 이 아닌가
# ------------------------------------
# Quick Tunnel 은 계정 없이 즉시 열리는 대신 재기동할 때마다 주소가 바뀐다.
# 발표 자료에 주소를 적을 수 없고, Vercel 에 올린 PWA 의 API 주소도 매번
# 다시 빌드해야 한다. Named Tunnel 로 고정하려면 Cloudflare 에 등록된
# 도메인을 사야 한다.
#
# Tailscale Funnel 은 도메인 없이도 계정마다 고정된 이름을 준다.
#     https://<호스트>.<테일넷>.ts.net
# 무료이고, 진짜 인증서가 붙고, 접속 경고 페이지가 끼지 않는다.
#
# 공개 범위: Funnel 로 연 경로는 인터넷 전체에 열린다. API 는 토큰 인증이
# 걸려 있지만(api/routers/auth.py), 그래도 열려 있다는 사실은 알고 있어야
# 한다. 닫으려면  bash scripts/setup-funnel.sh --off
# =====================================================================
# pipefail 은 쓰지 않는다. `... | grep -q` 나 `| head` 처럼 뒤쪽이 파이프를
# 일찍 닫는 검사에서 앞쪽 명령이 SIGPIPE 로 죽고, 그게 조건 실패로 둔갑한다.
# (실제로 bootstrap-pi.sh 에서 구 백엔드 정지가 통째로 건너뛰어졌다.)
set -uo pipefail
set +o pipefail
set -e

TS="$HOME/.local/bin/tailscale"
SOCK="/run/user/$(id -u)/tailscaled.sock"
WEB_PORT=8501     # Streamlit 대시보드
API_PORT=8000     # FastAPI

say() { printf '\n\033[1;36m== %s\033[0m\n' "$*"; }
ts() { "$TS" --socket="$SOCK" "$@"; }

[ -x "$TS" ] || { echo "tailscale 이 없습니다: $TS" >&2; exit 1; }

if ! systemctl --user is-active --quiet tailscaled; then
  echo "tailscaled 가 꺼져 있습니다.  systemctl --user start tailscaled" >&2
  exit 1
fi

# ---------------------------------------------------------------------
if [ "${1:-}" = "--off" ]; then
  say "Funnel 닫기"
  ts funnel --https=443 off 2>/dev/null || true
  ts serve reset 2>/dev/null || true
  ts funnel status || true
  echo "닫았습니다. 노드는 테일넷에 남아 있습니다."
  exit 0
fi

# ---------------------------------------------------------------------
say "1/5  로그인 상태"
if ! ts status >/dev/null 2>&1 || ts status 2>&1 | grep -q "Logged out"; then
  echo "  아직 로그인되지 않았습니다. 아래를 실행하고 브라우저에서 인증하세요:"
  echo "      ~/.local/bin/tailscale --socket=$SOCK up --hostname=thermoshift"
  exit 1
fi
ts status | head -3 || true

DNSNAME="$(ts status --json | python3 -c \
  'import json,sys; print(json.load(sys.stdin)["Self"]["DNSName"].rstrip("."))')"
echo "  노드 이름: $DNSNAME"

# ---------------------------------------------------------------------
say "2/5  HTTPS 인증서 준비"
# 테일넷에서 HTTPS 를 처음 쓰면 관리 콘솔에서 한 번 켜야 한다.
# 켜져 있지 않으면 아래 명령이 안내 링크를 띄운다.
# tailscale cert 는 현재 디렉터리에 .crt/.key 를 떨군다. 개인키가 저장소에
# 남으면 안 되므로 임시 디렉터리에서 확인만 하고 지운다. Funnel 자체는
# 인증서를 알아서 관리하므로 이 파일들이 필요하지는 않다.
CERT_TMP="$(mktemp -d)"
trap 'rm -rf "$CERT_TMP"' EXIT
if ! (cd "$CERT_TMP" && ts cert "$DNSNAME") >/dev/null 2>&1; then
  echo "  인증서를 아직 발급할 수 없습니다."
  echo "  관리 콘솔에서 HTTPS 를 켜 주세요:"
  echo "      https://login.tailscale.com/admin/dns  →  HTTPS Certificates  →  Enable"
  echo "  켠 뒤 이 스크립트를 다시 실행하세요."
  exit 1
fi
echo "  발급 가능"

# ---------------------------------------------------------------------
say "3/5  Funnel 권한"
# Funnel 은 테일넷 정책에서 따로 켜야 한다. 권한이 없는 상태에서
# `tailscale funnel --bg` 를 부르면 응답 없이 멈춰 버리므로, 노드 권한을
# 먼저 보고 없으면 활성화 링크를 뽑아 안내한다.
if ! ts status --json | python3 -c \
     'import json,sys; sys.exit(0 if any("funnel" in k for k in (json.load(sys.stdin)["Self"].get("CapMap") or {})) else 1)'; then
  echo "  이 테일넷에는 Funnel 이 꺼져 있습니다."
  LINK_LOG="$(mktemp)"
  "$TS" --socket="$SOCK" funnel "$WEB_PORT" > "$LINK_LOG" 2>&1 &
  LINK_PID=$!
  for _ in $(seq 1 15); do
    grep -q "login.tailscale.com/f/funnel" "$LINK_LOG" && break
    sleep 1
  done
  kill "$LINK_PID" 2>/dev/null || true
  echo
  sed -n '/To enable/,$p' "$LINK_LOG" | sed 's/^/  /'
  rm -f "$LINK_LOG"
  echo
  echo "  위 주소를 열어 켠 뒤 이 스크립트를 다시 실행하세요."
  echo
  echo "  참고: 지금도 테일넷 안에서는 접속됩니다 (같은 계정으로 로그인된 기기)."
  echo "        https://${DNSNAME}"
  exit 1
fi
echo "  켜져 있음"

# ---------------------------------------------------------------------
say "4/5  경로 연결"
# 한 호스트 이름 아래에 대시보드와 API 를 같이 둔다. 포트를 따로 쓰면
# (:8443 같은) 주소가 지저분하고, 기관 네트워크에서 막히는 일이 있다.
#
#   /      → Streamlit 대시보드
#   /api   → FastAPI  (Funnel 이 /api 접두사를 떼고 넘긴다)
ts serve reset 2>/dev/null || true
ts funnel --bg --set-path=/api "http://127.0.0.1:${API_PORT}"
ts funnel --bg "http://127.0.0.1:${WEB_PORT}"

# ---------------------------------------------------------------------
say "5/5  결과"
ts funnel status
cat <<EOF

  고정 주소 (재부팅해도 바뀌지 않습니다)

      대시보드   https://${DNSNAME}
      API        https://${DNSNAME}/api

  프론트가 쓸 환경변수:
      THERMOSHIFT_API_URL=https://${DNSNAME}/api

  아직 8501·8000 에 아무것도 없으면 502 가 뜹니다. 서비스를 먼저 올리세요:
      bash scripts/services.sh up
EOF
