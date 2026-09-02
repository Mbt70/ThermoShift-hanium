#!/bin/bash
# [미사용 — 2026-09-02] API·DB를 EC2로 직접 옮기는 방식(B안)으로 전환하며
# 이 리버스 SSH 터널(파이 API → EC2)은 더 이상 쓰지 않는다. 사유는
# docs/decision-log.md 2026-09-02 항목 참고. 삭제하지 않고 보존만 함.
#
# 파이에서 실행. EC2로 나가는 리버스 SSH 터널을 만든다.
#
#   bash infra/tunnel/setup.sh <EC2-주소> [원격사용자]
#
# 파이가 바깥으로 나가는 연결만 쓰므로 공인 IP·포트포워딩이 필요 없다.
set -euo pipefail

EC2_HOST="${1:-}"
REMOTE_USER="${2:-ubuntu}"
KEY_PATH="$HOME/.ssh/thermoshift_ec2"
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

if [ -z "$EC2_HOST" ]; then
  echo "사용법: bash infra/tunnel/setup.sh <EC2-주소> [원격사용자]" >&2
  echo "  예:   bash infra/tunnel/setup.sh 3.15.27.99 ubuntu" >&2
  exit 1
fi

echo "1) autossh 설치"
if ! command -v autossh >/dev/null; then
  sudo apt-get update -qq && sudo apt-get install -y autossh
fi

echo "2) 전용 SSH 키 준비"
if [ ! -f "$KEY_PATH" ]; then
  ssh-keygen -t ed25519 -N "" -C "thermoshift-pi-tunnel" -f "$KEY_PATH"
  echo
  echo "   새 키를 만들었습니다. 아래 공개키를 EC2의"
  echo "   ~$REMOTE_USER/.ssh/authorized_keys 에 추가하세요:"
  echo
  sed 's/^/     /' "$KEY_PATH.pub"
  echo
  read -r -p "   추가하셨으면 Enter를 누르세요..."
fi

echo "3) 연결 확인"
if ! ssh -i "$KEY_PATH" -o StrictHostKeyChecking=accept-new -o BatchMode=yes \
     -o ConnectTimeout=10 "$REMOTE_USER@$EC2_HOST" true; then
  echo "   EC2에 접속하지 못했습니다. 공개키 등록과 보안그룹(22번 포트)을 확인하세요." >&2
  exit 1
fi
echo "   접속 성공"

echo "4) 서비스 등록"
TMP="$(mktemp)"
sed -e "s|<EC2-주소>|$EC2_HOST|" -e "s|ubuntu@|$REMOTE_USER@|" \
    "$REPO/infra/tunnel/thermoshift-tunnel.service" > "$TMP"
sudo cp "$TMP" /etc/systemd/system/thermoshift-tunnel.service
rm -f "$TMP"
sudo systemctl daemon-reload
sudo systemctl enable --now thermoshift-tunnel

sleep 3
echo
echo "완료. 상태 확인:"
echo "  systemctl status thermoshift-tunnel"
echo
echo "EC2에서 아래가 응답하면 터널이 살아 있는 것입니다:"
echo "  curl http://127.0.0.1:18100/health"
