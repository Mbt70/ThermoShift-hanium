# Decision Log

프로젝트 주요 결정을 기록합니다.

| Date | Decision | Reason | Owner |
|---|---|---|---|
| 2026-05-03 | Repository baseline 문서 구조 생성 | 팀 협업과 개발 시작을 빠르게 하기 위해 | Jongmin |
| 2026-09-02 | API·DB를 라즈베리파이에서 EC2로 이전 | 파이 장애 시 서비스 전체가 멈추는 문제, SD카드 단일 저장 위험 | 조하늘 |
| 2026-09-02 | 게이트웨이에 로컬 SQLite 버퍼 추가 | 파이·EC2 사이 Tailscale 구간이 끊기면 측정값·판단이 유실되던 문제 | 조하늘 |

## 기록 방법

아래 형식으로 추가합니다.

```text
### YYYY-MM-DD - 결정 제목

- 결정:
- 이유:
- 대안:
- 영향:
- 담당:
```

### 2026-09-02 - API·DB를 EC2로 이전 (Tailscale 사설망 경유)

- 결정: PostgreSQL과 FastAPI(`api/`)를 라즈베리파이에서 EC2(t3.small, Ubuntu
  26.04)로 옮긴다. 라즈베리파이는 센서 수집·MQTT 브로커·IR 제어·로컬 SQLite
  버퍼만 담당한다. 파이 ↔ EC2 통신은 Tailscale 사설망을 쓰고, 외부 공개는
  (현재는 미적용, 추후) 파이가 아닌 EC2에서 Tailscale Funnel로 연다.
- 이유:
  - 파이가 꺼지거나 재부팅되면 API·DB까지 함께 멈춰 서비스 전체가 중단됨
  - 센서 원본 데이터가 SD카드에만 존재해 파이 고장 시 유실 위험이 큼
  - 심의 신청 내역(EC2 내 MQTT·API·DB 구동)과 실제 구성을 맞출 필요
- 대안:
  - AWS 계정 발급 전에는 고정 주소 확보를 위해 Cloudflare 터널과, 파이의
    API를 리버스 SSH 터널로 EC2까지 넘겨 EC2에서 프록시만 하는 방식(A안,
    `infra/ec2/setup.sh` + `infra/tunnel/`, 커밋 `c1369ab` 2026-08-25,
    김종민)을 썼음
  - AWS 계정 발급 후에는 API·DB 자체를 EC2로 옮기는 이번 방식(B안)으로
    전환. A안 전용이라 B안에서는 쓰지 않는 파일들 — 삭제하지 않고 아래만
    남겨둠(파일 자체는 안 건드림, 여기 한 곳에만 기록):
    - `infra/tunnel/setup.sh`, `infra/tunnel/thermoshift-tunnel.service`
      (파이→EC2 리버스 SSH 터널) — 파일 상단에 미사용 표시 추가함
    - `infra/ec2/setup.sh` (arm64 전제 Caddy+대시보드 설치 스크립트) —
      파일 상단에 미사용 표시 추가함
    - `infra/ec2/Caddyfile`, `infra/ec2/thermoshift-web.service` — 위
      setup.sh가 설치 대상으로 참조하는 부속 파일이라 마찬가지로 B안에서는
      안 쓰임. 이 둘은 파일 자체를 건드리지 않았음(표시 없음) — 정리는
      나중에 이 로그를 참고해서 할 것
- 영향:
  - 신규: `Dockerfile`, `.dockerignore`, `infra/docker-compose.ec2.yml`,
    `docs/deployment.md`
  - `infra/docker-compose.yml`(로컬 개발용)은 그대로 유지, 서버용은
    `infra/docker-compose.ec2.yml`로 분리
  - `.env.example`에 EC2 배포 시 바뀌는 값(DB_HOST, DB_PASSWORD,
    THERMOSHIFT_API_URL) 주석 추가
- 담당: 조하늘

### 2026-09-02 - 게이트웨이 로컬 SQLite 버퍼

- 결정: `gateway/app/storage.py`의 쓰기 메서드(센서값·재실추정·제어판단·
  IR이벤트·시스템이벤트)가 PostgreSQL 연결에 실패하면 예외를 던지는 대신
  `gateway/app/local_buffer.py`(SQLite, 파이 로컬 디스크)에 순서대로 쌓고,
  연결이 돌아오면 매 제어 주기(`storage.flush_pending()`)마다 순서대로
  재전송한다. `_drain_command_queue`(수동 명령 큐 조회)와
  `controller.decide()`의 `resolve_room_id`/예약 조회처럼 버퍼링 대상이
  아닌 읽기 경로도 DB 실패 시 예외를 삼키고 그 주기만 건너뛰도록 고쳤다 —
  안 그러면 그 앞단 실패 때문에 뒤에 있는(버퍼링되는) 쓰기까지 통째로
  스킵됐다.
- 이유: EC2 이전(위 항목) 이후 게이트웨이(파이)와 PostgreSQL(EC2)이
  Tailscale 사설망을 넘어 통신하게 됐다. 이전에는 같은 파이 안의 로컬
  접속이라 끊길 일이 거의 없었지만, 이제는 네트워크 구간이 실제로 생겨서
  거기서 끊기면 서비스는 안 죽어도 그 시간 동안의 데이터가 조용히
  유실됐다.
- 대안: 이전에 비슷한 로컬 버퍼를 만들었다가 지운 적이 있다고 하는데,
  git 이력(`git log --all -p -- gateway/`)에는 그 코드가 남아 있지 않음 —
  찾은 건 PostgreSQL 이관 전 SQLite를 단일 저장소로 쓰던 구버전
  코드(커밋 `e94dc27`, "게이트웨이를 PostgreSQL 스키마로 이식")뿐이고,
  이건 "오프라인 버퍼"가 아니라 그 자체가 유일한 저장소였던 다른 설계라
  그대로 되살릴 수 없었음. 그래서 새로 작성함.
- 영향:
  - 신규: `gateway/app/local_buffer.py`
  - 수정: `gateway/app/storage.py`(버퍼링 래퍼 `_write_or_buffer`,
    `flush_pending`), `gateway/app/controller.py`,
    `gateway/app/main.py`(주기마다 `flush_pending` 호출)
  - `gateway/data/`(SQLite 파일 위치)를 `.gitignore`에 추가
  - 알려진 한계: 오프라인 중 버퍼링된 `occupancy_estimates`가 재전송돼
    새 `estimate_id`를 받으면, 같은 주기에 함께 버퍼링된
    `control_decisions.estimate_id`는 그 값을 모른 채 이미 NULL로
    나갔을 수 있음 (nullable이라 판단 자체는 남지만 AI 해설의 근거
    연결만 못 함)
- 담당: 조하늘
