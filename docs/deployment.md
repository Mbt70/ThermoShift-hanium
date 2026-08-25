# 배포 — 외부에서 실제 제어하기

목표: Vercel에 올라간 웹/앱에서 **실제로 에어컨을 제어**하고 **실시간 수치**를 본다.

## 먼저 알아야 할 제약

**클라우드는 에어컨에 IR을 쏠 수 없습니다.** 제어 실행은 현장의 라즈베리파이만
할 수 있고, 이건 어떤 호스팅을 써도 바뀌지 않습니다.

그래서 클라우드가 맡을 수 있는 역할은 셋뿐입니다.

| 역할 | 필요한 시점 |
|---|---|
| 외부 접속 창구 | 지금 (Vercel 프론트가 API를 불러야 함) |
| 데이터 보관·조회 | 파이가 꺼져도 데이터를 봐야 할 때 |
| 무거운 연산 (CFD 사전계산, AI) | 3D 시각화·AI를 붙일 때 |

핵심은 **밖에서 파이로 들어갈 길**을 만드는 것입니다. 서버를 사는 것과는
별개의 문제이고, 서버가 있어도 이 통로는 따로 뚫어야 합니다.

## 준비: 보안 확인

외부에 열기 전에 반드시 확인합니다.

- [ ] API에 토큰 인증이 켜져 있다 (`api/app/auth.py`) — 기본 적용됨
- [ ] `THERMOSHIFT_SECRET_KEY` 를 지정했거나, 자동 생성된 `secret.key` 가
      DB 옆에 0600 권한으로 있다
- [ ] `THERMOSHIFT_ALLOWED_ORIGINS` 에 프론트 도메인만 지정했다
      (와일드카드면 서버 로그에 경고가 뜬다)
- [ ] `ANTHROPIC_API_KEY` 는 **서버에만** 있다. 프론트 빌드에 넣지 않았다
- [ ] gateway 가 `shadow` 모드다 (IR 코드를 학습하기 전까지)

```bash
# 예시
export THERMOSHIFT_SECRET_KEY="$(openssl rand -hex 32)"
export THERMOSHIFT_ALLOWED_ORIGINS="https://thermoshift.vercel.app"
```

---

## 방법 A — EC2 + 리버스 SSH 터널 (권장)

EC2를 **시스템의 복사본이 아니라 공개 창구**로 씁니다. 데이터 원본과 제어는
파이에 그대로 두므로 동기화 문제가 아예 생기지 않습니다.

```text
인터넷 ──HTTPS──> EC2 (탄력적 IP)
                    │ Caddy (자동 인증서)
                    ├─ /       → Streamlit 대시보드 (EC2에서 서버 렌더링)
                    └─ /api/*  → 리버스 SSH 터널 ──> 파이 :8100
                                                        ↓
                                                 gateway → IR → 에어컨
```

이 구조를 고른 이유

- **데이터 동기화가 필요 없습니다.** 원본 SQLite는 파이 하나뿐입니다.
- **AI 키를 안전하게 둘 수 있습니다.** 대시보드가 서버에서 렌더링되므로
  키가 브라우저로 나가지 않습니다. stlite 로는 불가능한 일입니다.
- **stlite 제약이 사라집니다.** 진짜 WebSocket, 빠른 로딩, 정상적인 인증.
- 파이는 **아웃바운드 연결만** 씁니다. 공인 IP·포트포워딩·학교 방화벽 협의가
  필요 없습니다.
- 터널은 EC2의 **루프백에만** 바인딩합니다. API가 인터넷에 직접 노출되지
  않고, Caddy 를 거친 요청만 파이에 닿습니다.

한계: 파이가 꺼지면 `/api/*` 가 502 를 냅니다. 어차피 파이가 꺼지면 에어컨
제어도 불가능하므로 실질적인 손해는 데이터 조회뿐입니다. 이게 문제가 되면
아래 "나중에" 절의 MQTT 브리지를 붙입니다.

### 1) EC2 준비

인스턴스는 **t4g.small (2 vCPU ARM, 2GB)** 이면 충분합니다. 파이와 같은
aarch64 라 파이썬 휠도 동일하게 동작합니다.

보안그룹에서 **22(SSH), 80(HTTP, 인증서 발급용), 443(HTTPS)** 만 엽니다.
그 외 포트는 열지 않습니다.

```bash
# EC2에 접속해서
git clone https://github.com/Mbt70/ThermoShift-hanium.git
cd ThermoShift-hanium
bash infra/ec2/setup.sh <도메인>
```

도메인이 없으면 **sslip.io** 를 쓰면 됩니다. EC2 공인 IP의 점을 하이픈으로
바꾼 주소가 그대로 DNS 이름이 되고, Let's Encrypt 인증서도 발급됩니다.

```bash
# 공인 IP가 3.15.27.99 라면
bash infra/ec2/setup.sh 3-15-27-99.sslip.io
```

### 2) 파이에서 터널 켜기

```bash
cd ~/ThermoShift-hanium
bash infra/tunnel/setup.sh <EC2 공인 IP>
```

스크립트가 전용 SSH 키를 만들고 공개키를 출력합니다. 그 키를 EC2의
`~/.ssh/authorized_keys` 에 추가한 뒤 Enter 를 누르면 서비스가 등록됩니다.
연결이 끊기면 `autossh` 가 자동으로 다시 붙습니다.

### 3) 확인

```bash
# EC2에서
curl http://127.0.0.1:18100/api/health   # 터널 확인
curl https://<도메인>/api/health          # 전체 경로 확인
```

브라우저에서 `https://<도메인>` 을 열면 대시보드가 뜹니다.

### Vercel 앱도 함께 쓰려면

Caddy 가 `/api/*` 를 공개하므로 Vercel 앱도 같은 주소를 쓸 수 있습니다.

| 위치 | 설정 |
|---|---|
| Vercel 환경변수 | `THERMOSHIFT_API_BASE=https://<도메인>` |
| 파이 API | `THERMOSHIFT_ALLOWED_ORIGINS=https://<프로젝트>.vercel.app` |

대시보드는 EC2에서 서버 렌더링되므로 CORS와 무관합니다. CORS가 필요한 쪽은
브라우저에서 도는 Vercel 앱뿐입니다.

---

## 방법 B — Cloudflare Tunnel (EC2 없이, 0원)

EC2를 쓰지 않거나 잠시 멈춰 둘 때의 대안입니다. 원리는 같습니다 — 파이가
바깥으로 나가는 연결만 씁니다.

```bash
curl -L -o /tmp/cloudflared.deb \
  https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-arm64.deb
sudo dpkg -i /tmp/cloudflared.deb
cloudflared tunnel login
cloudflared tunnel create thermoshift
cloudflared tunnel route dns thermoshift api.<도메인>
sudo cp infra/cloudflared/config.yml /etc/cloudflared/config.yml   # 터널ID·도메인 수정
sudo cloudflared service install && sudo systemctl enable --now cloudflared
```

이 경우 대시보드는 Vercel(stlite)에 남으므로, AI 키를 프론트에 둘 수 없다는
제약이 그대로입니다. AI 기능은 파이의 API가 대신 호출합니다.

---

## 나중에 — MQTT 브리지 (파이가 꺼져도 데이터 보관)

파이가 오프라인일 때도 과거 데이터를 조회해야 하거나, 실증 공간이 여러 곳으로
늘어나면 텔레메트리를 클라우드에 적재합니다.

```text
ESP32 → 파이(mosquitto + gateway) ──MQTT bridge(TLS, 아웃바운드)──> EC2
             ↓ 로컬 SQLite                                          ↓
        IR 제어 (오프라인에도 동작)                     mosquitto → 수집기 → DB
```

설정 예시는 [`infra/mqtt/bridge.conf`](../infra/mqtt/bridge.conf) 에 있습니다.
클라우드 브로커는 반드시 TLS(8883) + 인증을 켜야 합니다. 평문 1883 을 공인
IP에 열면 누구나 제어 토픽을 발행할 수 있습니다.

EC2에 적재하려면 브리지된 MQTT를 구독해 EC2의 DB에 쓰는 수집기가 필요하고,
제어 명령은 반대 방향으로 흘려보내야 합니다. **방법 A보다 확실히 손이 많이
갑니다.** 데이터 보관이 실제로 필요해지기 전에는 미루는 편이 낫습니다.

---

## 예산 배분 제안 (38만원 기준)

EC2 t4g.small 은 이미 구매한 상태를 전제로 합니다.

| 항목 | 금액 | 비고 |
|---|---|---|
| **스마트 플러그 2개** | **5만원** | **KPI '에너지 절감' 증명에 필수** |
| EC2 t4g.small (구매 완료) | 월 약 1.7만원 | 3개월 약 5만원. 온디맨드 기준 |
| EBS 20GB gp3 | 월 약 2천원 | |
| CFD 사전계산 (EC2 스팟 20시간) | 3만원 | 상시 인스턴스 말고 스팟으로 |
| Claude API 크레딧 | 5만원 | 실제 예상 월 1~2만원 |
| 도메인 (.com 1년) | 2만원 | 선택 — sslip.io 로 대체 가능 |
| 예비 | 17만원 | 센서 추가·교체 |

**비용을 줄이는 법 두 가지**

- 발표·시연 기간 외에는 EC2를 **중지(stop)** 해 두면 인스턴스 요금이 멈춥니다
  (EBS 요금만 남습니다). 탄력적 IP는 인스턴스가 멈춰 있으면 과금되므로,
  자주 멈출 계획이면 sslip.io + 재시작 시 IP 갱신이 오히려 편합니다.
- 1년 이상 쓸 계획이면 Savings Plan 으로 30~40% 절감됩니다. 한이음 기간만
  쓸 거라면 온디맨드가 맞습니다.

**예산을 클라우드에 다 쓰면 안 됩니다.** 지금 프로젝트의 병목은 연산이 아니라
측정입니다.

- 제어 판단 2,376건 중 **2,276건(95.8%)이 `ENV_STALE`** — 센서 데이터가 낡아
  판단 자체가 불가능했습니다
- 재실로 판정된 시간 **1.4%** — OCC 노드(PIR·도어)가 사실상 데이터를 안 보냅니다
- 전력 실측이 없어 핵심 KPI를 증명할 수 없습니다

아무리 좋은 서버를 사도 이 셋은 풀리지 않습니다.

### Claude API 비용 감

| 기능 | 1회 비용 | 빈도 |
|---|---|---|
| 제어 근거 설명 | 약 30원 | 상세 화면을 열 때만 |
| 알림 진단 | 약 30원 | 상세 화면을 열 때만 |
| 주간 리포트 | 약 90원 | 주 1회 |

비용을 더 줄이려면 `THERMOSHIFT_AI_MODEL` 로 더 작은 모델을 지정할 수 있습니다.

---

## 확인

```bash
# 1) 파이에서 API가 살아 있는가
curl http://localhost:8100/api/health

# 2) EC2에서 터널이 살아 있는가
curl http://127.0.0.1:18100/api/health

# 3) 외부에서 전체 경로가 열렸는가
curl https://<도메인>/api/health
curl -X POST https://<도메인>/api/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"email":"...","password":"..."}'
# → token 이 나오면 정상
```

어디서 끊겼는지 위에서부터 확인하면 원인이 좁혀집니다.

| 증상 | 원인 |
|---|---|
| 1번 실패 | 파이의 `thermoshift-api` 서비스가 죽었다 |
| 1번 성공, 2번 실패 | 터널이 끊겼다 (`systemctl status thermoshift-tunnel`) |
| 2번 성공, 3번 실패 | Caddy 설정이나 보안그룹(443) 문제 |
