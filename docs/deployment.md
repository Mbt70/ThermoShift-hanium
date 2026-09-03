# EC2 배포 (PostgreSQL + API)

라즈베리파이가 꺼지면 서비스 전체가 멈추는 문제 때문에, PostgreSQL 과
FastAPI(`api/`)를 EC2로 옮긴 절차를 정리한다. 라즈베리파이는 센서 수집·MQTT
브로커·IR 제어를 그대로 맡는다. 전환 배경은
[`decision-log.md`](./decision-log.md) 참고.

이 문서는 `infra/docker-compose.ec2.yml` 기준이다. `infra/docker-compose.yml`
(로컬 개발용, postgres만 띄움)과는 다른 파일이니 헷갈리지 말 것.

## 사전 조건

EC2(t3.small, Ubuntu 26.04, x86_64) 기준으로 아래가 준비돼 있어야 한다.

- Docker, Docker Compose 플러그인 설치 (`docker compose version` 으로 확인)
- 스왑 2GB 이상 (`swapon --show` 로 확인 — t3.small 은 메모리가 넉넉하지 않음)
- 보안그룹: 22(SSH, 관리자 접속용)만 열려 있으면 됨. API(8000)는
  컨테이너를 `127.0.0.1` 로만 바인딩하므로 인바운드로 열 필요가 없다.
  외부 공개는 Tailscale(사설망)을 통해서 하고, 추후 Tailscale Funnel 로
  전환한다 — Funnel 은 아웃바운드 연결만 쓰므로 보안그룹에 추가로 열 포트가
  없다.
- git 설치

## 배포 절차

```bash
# 1) 저장소 클론
git clone https://github.com/Mbt70/ThermoShift-hanium.git
cd ThermoShift-hanium

# 2) .env 작성
cp .env.example .env
vi .env
#   - DB_HOST=postgres           (localhost 아님 — 컨테이너 서비스명)
#   - DB_PASSWORD=<새로 생성한 값>  (openssl rand -base64 24, thermoshift1234 금지)
#   - AUTH_SECRET=<새로 생성한 값>  (openssl rand -base64 32)
#   - CORS_ORIGINS=<실제 웹/PWA origin만 쉼표로 나열>
#   - THERMOSHIFT_API_URL 은 이 서버가 아니라 이 API를 "호출하는 쪽"
#     (web/app)이 쓰는 값이라 여기서는 비워둬도 무방
#   - GEMINI_API_KEY 는 AI 해설 기능을 쓸 경우에만

# 3) 빌드 + 기동
docker compose -f infra/docker-compose.ec2.yml --env-file .env up -d --build
```

기존 DB에 시연 계정 기능을 추가할 때는 볼륨을 다시 만들지 말고 마이그레이션을
한 번 적용한다.

```bash
docker cp db/007_demo_access.sql thermoshift-postgres:/tmp/007_demo_access.sql
docker exec thermoshift-postgres \
  psql -U thermoshift -d thermoshift -f /tmp/007_demo_access.sql

# 전용 시연 계정이 조회할 운영 계정을 연결한다. 이메일은 실제 값으로 바꾼다.
docker exec thermoshift-postgres psql -U thermoshift -d thermoshift -c \
  "UPDATE users SET is_demo=true,
   demo_owner_user_id=(SELECT user_id FROM users WHERE email='owner@example.com')
   WHERE email='demo@example.com';"
```

기존 DB에 센서 원문 보존 컬럼을 추가할 때도 볼륨을 지우지 않고 다음을 한 번
적용한다. 이미 적용된 DB에서 다시 실행해도 안전하다.

```bash
docker cp db/008_sensor_raw_payload.sql thermoshift-postgres:/tmp/008_sensor_raw_payload.sql
docker exec thermoshift-postgres \
  psql -v ON_ERROR_STOP=1 -U thermoshift -d thermoshift \
  -f /tmp/008_sensor_raw_payload.sql
```

EC2의 5432·8000 포트는 `127.0.0.1`에만 바인딩한다. 라즈베리파이는
`thermoshift-ec2-tunnel.service`의 SSH 포워딩(5433→5432, 8001→8000)을
사용하고, 공개 `/api` 경로는 로컬 8001을 통해 EC2 API로 전달한다.

## 헬스체크 확인

```bash
# postgres 컨테이너가 healthy 상태인지
docker compose -f infra/docker-compose.ec2.yml ps

# api 가 DB 에 실제로 붙었는지 (api/main.py 의 /health, SELECT 1 까지 확인)
curl http://127.0.0.1:8000/health
# {"status":"ok","db":"connected","check":1} 이면 정상
```

## 로그 · 재시작 · 중지

```bash
# 로그 (실시간)
docker compose -f infra/docker-compose.ec2.yml logs -f api
docker compose -f infra/docker-compose.ec2.yml logs -f postgres

# 재시작 (설정 변경 후 컨테이너만 다시 시작 — 이미지는 다시 안 만듦)
docker compose -f infra/docker-compose.ec2.yml restart api

# 코드 변경 후 이미지까지 새로 빌드
docker compose -f infra/docker-compose.ec2.yml --env-file .env up -d --build api

# 전체 중지 (볼륨은 남음 — DB 데이터 유지)
docker compose -f infra/docker-compose.ec2.yml down

# 완전히 지우기 (DB 데이터까지 삭제 — 주의)
docker compose -f infra/docker-compose.ec2.yml down -v
```

## 자주 나는 오류와 대응

**`api` 가 `connection refused` 로 죽어 있음**
`depends_on: condition: service_healthy` 로 postgres 가 healthy 해질 때까지
기다리긴 하지만, 최초 기동 시 `db/001~008` 초기화 스크립트
적용에 몇 초 더 걸릴 수 있다. `docker compose ps` 로 postgres 상태를 먼저
확인.

**`.env` 값을 바꿨는데 반영이 안 됨**
`environment:` 로 이미 떠 있는 postgres 컨테이너는 값을 다시 안 읽는다.
postgres 쪽 값(DB_USER/PASSWORD/NAME)을 바꾸려면 컨테이너를 새로 만들어야
하고, 이미 데이터가 쌓인 볼륨과 비밀번호가 어긋나면 인증 실패가 난다 —
운영 중인 DB 비밀번호는 함부로 바꾸지 말 것.

**`docker compose` 명령에서 `${DB_USER}` 등이 빈 값으로 치환됨**
`--env-file .env` 를 빠뜨리고 실행한 경우다. 반드시 저장소 루트에서
`--env-file .env` 를 붙여서 실행할 것 (본 문서의 모든 예시 명령 참고).
