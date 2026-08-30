#!/usr/bin/env bash
# =====================================================================
# fix-lan-dns.sh — 파이 핫스팟에 붙은 기기가 고정 도메인을 찾게 한다.
#
#   sudo bash scripts/fix-lan-dns.sh
#
# 문제
# ----
# 이 망의 상위 DNS(10.38.78.179 및 IPv6 쌍)는 *.ts.net 을 해석해 주지
# 않는다. github.com 은 정상이므로 DNS 가 고장난 게 아니라 Tailscale
# 도메인만 걸러지는 것이다.
#
#     thermoshift.tail46fe5e.ts.net  A    -> NOERROR 답변 0개
#                                    AAAA -> NXDOMAIN
#     github.com                     A    -> 정상
#
# 파이는 NetworkManager 공유연결(wlan0, 10.42.0.1)로 핫스팟을 돌리고
# 있고, 거기 붙은 PC 는 파이의 dnsmasq 를 DNS 로 쓴다. dnsmasq 는 위
# 상위 DNS 를 그대로 물어보므로 클라이언트도 똑같이 못 찾는다.
# 브라우저에는 "사이트에 연결할 수 없음" 으로 보인다.
#
# 고치는 방법
# -----------
# dnsmasq 에게 ts.net 만 공인 DNS 로 넘기라고 알려준다. 나머지 도메인은
# 지금처럼 사내 DNS 를 쓰므로 내부 주소 조회에 영향이 없다.
# =====================================================================
set -uo pipefail
set +o pipefail
set -e

if [ "$(id -u)" -ne 0 ]; then
  echo "sudo 로 실행하세요:  sudo bash scripts/fix-lan-dns.sh" >&2
  exit 1
fi

CONF_DIR=/etc/NetworkManager/dnsmasq-shared.d
CONF="$CONF_DIR/ts-net.conf"

[ -d "$CONF_DIR" ] || {
  echo "$CONF_DIR 이 없습니다. NetworkManager 공유연결이 아닌 것 같습니다." >&2
  exit 1; }

cat > "$CONF" <<'EOF'
# ts.net 만 공인 DNS 로 넘긴다.
#
# 이 망의 상위 DNS 는 *.ts.net 에 빈 응답/NXDOMAIN 을 주기 때문에, 파이
# 핫스팟에 붙은 기기가 Tailscale Funnel 주소를 찾지 못한다. 도메인을
# 한정해 넘기므로 사내 내부 주소 조회는 그대로 사내 DNS 를 쓴다.
server=/ts.net/1.1.1.1
server=/ts.net/8.8.8.8
EOF
echo "기록: $CONF"
cat "$CONF" | sed 's/^/    /'

# 공유연결을 다시 올려야 dnsmasq 가 새 설정을 읽는다. 연결 이름을 찾아
# 그것만 재기동한다 — NetworkManager 전체를 재시작하면 SSH 가 끊긴다.
CON="$(nmcli -t -f NAME,TYPE connection show --active | awk -F: '$2=="802-11-wireless"{print $1; exit}')"
if [ -n "${CON:-}" ]; then
  echo
  echo "공유연결 '$CON' 재기동 중..."
  nmcli connection down "$CON" >/dev/null 2>&1 || true
  sleep 2
  nmcli connection up "$CON" >/dev/null 2>&1 || true
  sleep 3
else
  echo
  echo "무선 공유연결을 찾지 못했습니다. dnsmasq 를 직접 다시 읽힙니다."
  pkill -HUP -F /run/nm-dnsmasq-wlan0.pid 2>/dev/null || true
fi

echo
echo "확인:"
sleep 2
python3 - <<'PY'
import socket, struct, random
n = "thermoshift.tail46fe5e.ts.net"
tid = random.randint(0, 65535)
q = struct.pack(">HHHHHH", tid, 0x0100, 1, 0, 0, 0)
for p in n.split("."):
    q += bytes([len(p)]) + p.encode()
q += b"\x00" + struct.pack(">HH", 1, 1)
s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM); s.settimeout(6)
try:
    s.sendto(q, ("10.42.0.1", 53))
    d, _ = s.recvfrom(4096)
    an = struct.unpack(">H", d[6:8])[0]
    rc = d[3] & 0x0F
    print(f"    10.42.0.1 -> rcode={rc} 답변 {an}개",
          "  성공" if (rc == 0 and an > 0) else "  아직 실패")
except Exception as e:
    print("    질의 실패:", e)
PY
echo
echo "PC 에서 DNS 캐시를 비운 뒤 다시 접속해 보세요:"
echo "    Windows:  ipconfig /flushdns"
