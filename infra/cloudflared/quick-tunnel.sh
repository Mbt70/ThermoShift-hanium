#!/bin/bash
# Cloudflare Quick Tunnel — 계정도 도메인도 없이 즉시 외부 공개.
#
#   bash infra/cloudflared/quick-tunnel.sh          # 대시보드(8501) 공개
#   bash infra/cloudflared/quick-tunnel.sh 8100     # API 공개
#
# 주의: 재시작할 때마다 주소가 바뀝니다. 발표처럼 주소가 고정돼야 하는
#       상황에서는 Named Tunnel 을 쓰세요 (docs/deployment.md).
#
# root 권한이 필요 없습니다. cloudflared 바이너리를 ~/.local/bin 에 둡니다.
set -euo pipefail

PORT="${1:-8501}"
BIN="$HOME/.local/bin/cloudflared"

if [ ! -x "$BIN" ]; then
  echo "cloudflared 내려받는 중..."
  mkdir -p "$(dirname "$BIN")"
  curl -sL -o "$BIN" \
    https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-arm64
  chmod +x "$BIN"
fi

LOG="$(mktemp /tmp/cloudflared-XXXXXX.log)"
"$BIN" tunnel --no-autoupdate --url "http://127.0.0.1:$PORT" > "$LOG" 2>&1 &
PID=$!

echo "터널 여는 중 (포트 $PORT)..."
URL=""
for _ in $(seq 1 30); do
  URL="$(grep -oE 'https://[a-z0-9-]+\.trycloudflare\.com' "$LOG" | head -1 || true)"
  [ -n "$URL" ] && break
  sleep 1
done

if [ -z "$URL" ]; then
  echo "주소 발급에 실패했습니다. 로그: $LOG" >&2
  kill "$PID" 2>/dev/null || true
  exit 1
fi

echo
echo "  공개 주소: $URL"
echo "  프로세스 : $PID   (끄려면 kill $PID)"
echo "  로그     : $LOG"
