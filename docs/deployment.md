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

지금 막혀 있는 건 **서버가 없어서가 아니라, 밖에서 파이로 들어갈 길이 없어서**
입니다. 이건 서버를 사도 해결되지 않고, 서버 없이도 해결됩니다.

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

## 방법 A — Cloudflare Tunnel (권장, 0원, 30분)

파이에서 **바깥으로 나가는 연결만** 쓰기 때문에 공인 IP도, 포트포워딩도,
학교 방화벽 협의도 필요 없습니다. 학교 네트워크에서는 이게 결정적입니다.

```text
Vercel 앱 ──HTTPS──> api.<도메인> ──터널──> 파이 :8100
                     (Cloudflare)              ↓
                                        gateway → IR → 에어컨
```

### 설치

```bash
# 1) cloudflared 설치 (arm64)
curl -L -o /tmp/cloudflared.deb \
  https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-arm64.deb
sudo dpkg -i /tmp/cloudflared.deb

# 2) Cloudflare 계정 로그인 (브라우저가 열립니다)
cloudflared tunnel login

# 3) 터널 생성
cloudflared tunnel create thermoshift

# 4) 도메인 연결 (Cloudflare에 등록된 도메인 필요)
cloudflared tunnel route dns thermoshift api.<도메인>

# 5) 설정 파일 배치 후 서비스 등록
sudo cp infra/cloudflared/config.yml /etc/cloudflared/config.yml
sudo cloudflared service install
sudo systemctl enable --now cloudflared
```

설정 예시는 [`infra/cloudflared/config.yml`](../infra/cloudflared/config.yml)에 있습니다.

### Vercel 연결

Vercel 프로젝트 설정 → Environment Variables 에 추가한 뒤 재배포합니다.

| 이름 | 값 |
|---|---|
| `THERMOSHIFT_API_BASE` | `https://api.<도메인>` |

그리고 파이에서 CORS 허용 출처를 좁힙니다.

```bash
sudo systemctl edit thermoshift-api
# [Service]
# Environment="THERMOSHIFT_ALLOWED_ORIGINS=https://<프로젝트>.vercel.app"
sudo systemctl restart thermoshift-api
```

여기까지 하면 **휴대폰에서 실제 제어 + 실시간 수치**가 됩니다.

---

## 방법 B — AWS (CFD·AI를 본격적으로 붙일 때)

### 무엇을 사야 하나

**Lightsail 2GB 플랜 ($12/월, 서울 리전 ap-northeast-2)** 을 권합니다.

| | Lightsail 2GB | EC2 t4g.small |
|---|---|---|
| 월 비용 | $12 정액 | $12.3 + EBS + 전송량 |
| 고정 IP | 포함 | Elastic IP 별도 |
| 데이터 전송 | 3TB 포함 | 종량 과금 |
| 예산 사고 위험 | 낮음 | 전송량 과금이 튈 수 있음 |

학생 프로젝트에서는 **정액제가 예산 사고를 막아 줍니다.** EC2는 데이터 전송
요금이 예상 밖으로 커지는 사례가 흔합니다.

CFD 사전계산처럼 무거운 배치는 상시 인스턴스가 아니라 **필요할 때만 EC2 스팟**
(예: `c7g.4xlarge` 스팟, 시간당 약 $0.2)을 몇 시간 띄우는 편이 훨씬 쌉니다.

### 구조

파이는 로컬 제어를 계속하고, 텔레메트리만 클라우드로 올립니다.
**인터넷이 끊겨도 냉방 제어는 멈추지 않습니다.**

```text
ESP32 → 파이(mosquitto + gateway) ──MQTT bridge(TLS, 아웃바운드)──> AWS
             ↓ 로컬 SQLite                                          ↓
        IR 제어 (오프라인에도 동작)                    mosquitto + api + web
                                                              ↑
                                                        Vercel / 브라우저
```

MQTT 브리지도 **파이에서 바깥으로 나가는 연결**이라 포트포워딩이 필요 없습니다.
설정 예시는 [`infra/mqtt/bridge.conf`](../infra/mqtt/bridge.conf)에 있습니다.

### 남는 일

클라우드에 API를 올리면 데이터가 파이의 SQLite에 있다는 문제가 생깁니다.
브리지된 MQTT를 구독해 클라우드 DB에 적재하는 수집기가 필요하고, 제어 명령은
반대 방향으로 흘려보내야 합니다. **방법 A보다 확실히 손이 많이 갑니다.**
CFD나 AI 부하가 실제로 커지기 전에는 굳이 갈 필요가 없습니다.

---

## 예산 배분 제안 (38만원 기준)

| 항목 | 금액 | 비고 |
|---|---|---|
| **스마트 플러그 2개** | **5만원** | **KPI '에너지 절감' 증명에 필수** |
| Lightsail 2GB × 3개월 | 5만원 | 방법 B로 갈 때만 |
| CFD 사전계산 (EC2 스팟 20시간) | 3만원 | 시나리오 배치 |
| Claude API 크레딧 | 5만원 | 실제 예상 월 1~2만원 |
| 도메인 (.com 1년) | 2만원 | 선택 |
| 예비 | 18만원 | 센서 추가·교체 |

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
curl https://api.<도메인>/api/health
curl -X POST https://api.<도메인>/api/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"email":"...","password":"..."}'
# → token 이 나오면 정상
```
