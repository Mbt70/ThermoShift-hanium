#!/bin/bash
# EC2(Ubuntu, arm64)에서 실행. Caddy + 대시보드를 올린다.
#
#   bash setup.sh <도메인>
#
# 도메인이 없으면 sslip.io 를 쓸 수 있다 (EC2 공인 IP의 점을 하이픈으로):
#   bash setup.sh 3-15-27-99.sslip.io
set -euo pipefail

DOMAIN="${1:-}"
REPO_URL="${THERMOSHIFT_REPO:-https://github.com/Mbt70/ThermoShift-hanium.git}"
REPO_DIR="$HOME/ThermoShift-hanium"

if [ -z "$DOMAIN" ]; then
  echo "사용법: bash setup.sh <도메인>" >&2
  exit 1
fi

echo "1) 패키지 설치"
sudo apt-get update -qq
sudo apt-get install -y python3-venv git curl debian-keyring debian-archive-keyring apt-transport-https

if ! command -v caddy >/dev/null; then
  curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' \
    | sudo gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
  curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' \
    | sudo tee /etc/apt/sources.list.d/caddy-stable.list >/dev/null
  sudo apt-get update -qq && sudo apt-get install -y caddy
fi

echo "2) 저장소 준비"
if [ ! -d "$REPO_DIR" ]; then
  git clone "$REPO_URL" "$REPO_DIR"
fi
cd "$REPO_DIR"

echo "3) 가상환경 (대시보드만 띄우므로 프론트 의존성만)"
[ -d .venv ] || python3 -m venv .venv
.venv/bin/pip install --quiet --upgrade pip
.venv/bin/pip install --quiet -r requirements.txt

echo "4) Caddy 설정"
sudo mkdir -p /var/log/caddy
sed "s|<도메인>|$DOMAIN|" infra/ec2/Caddyfile | sudo tee /etc/caddy/Caddyfile >/dev/null
sudo systemctl enable --now caddy
sudo systemctl reload caddy

echo "5) 대시보드 서비스"
sudo cp infra/ec2/thermoshift-web.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now thermoshift-web

echo
echo "완료."
echo "  대시보드: https://$DOMAIN"
echo "  API     : https://$DOMAIN/api/health  (파이 터널이 살아 있어야 응답)"
echo
echo "다음으로 파이에서 터널을 켜세요:"
echo "  bash infra/tunnel/setup.sh <이 EC2의 공인 IP>"
echo
echo "보안그룹에서 열어야 할 포트: 22(SSH), 80(HTTP, 인증서 발급), 443(HTTPS)"
