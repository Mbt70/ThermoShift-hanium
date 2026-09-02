# Decision Log

프로젝트 주요 결정을 기록합니다.

| Date | Decision | Reason | Owner |
|---|---|---|---|
| 2026-05-03 | Repository baseline 문서 구조 생성 | 팀 협업과 개발 시작을 빠르게 하기 위해 | Jongmin |
| 2026-09-02 | API·DB를 라즈베리파이에서 EC2로 이전 | 파이 장애 시 서비스 전체가 멈추는 문제, SD카드 단일 저장 위험 | 조하늘 |

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
