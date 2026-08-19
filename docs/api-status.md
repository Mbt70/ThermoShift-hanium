# API 구현 현황

DB 스키마(`db/002_tables.sql`, 15개 테이블) 기준으로 어떤 부분이 API로 노출됐고 어떤 부분이 아직 없는지 정리한 문서. 다음 작업자가 API를 이어서 만들 때 여기부터 보면 됨.

## 구현됨 (`api/routers/`, 총 28개 엔드포인트)

| 라우터 | 대응 테이블 | 기능 |
|---|---|---|
| `auth.py` | `users` | 회원가입/로그인/조회/이름·비번 수정/탈퇴 |
| `rooms.py` | `rooms`, `sensor_env`, `power_readings`, `occupancy_estimates` (조회만) | 공간 CRUD, 최신 센서값(`/latest`), 30분 추이(`/trend`) |
| `devices.py` | `devices` | 공간별 디바이스 목록, 활성화 토글 |
| `schedules.py` | `schedules` | 예약 냉방 CRUD |
| `control.py` | `hvac_commands` (조회만) | 제어 로그 조회 |
| `events.py` | `event_logs` | 알림/이벤트 조회, 읽음 처리 |
| `inquiries.py` | `inquiries` | 1:1 문의 등록·조회 (앱 제어 로그 상세에서 접수) |

## 미구현

DB 테이블은 있는데 API 엔드포인트가 없는 부분:

- **센서 데이터 수신(ingestion)** - `sensor_env` / `sensor_pir` / `sensor_door` / `power_readings`에 값을 **넣는** `POST`가 없음. 실증 하드웨어나 시뮬레이터가 쏴야 할 부분. (지금까지 테스트는 DB에 직접 SQL INSERT해서 흉내 냄)
- **HVAC 명령 발행** - `control.py`는 조회(`GET`)만 있고, 실제로 명령을 내리는 `POST /rooms/{id}/commands` 같은 게 없음. `hvac_commands` INSERT + IR 송신 트리거 + `power_before`/`power_after` 검증 로직 필요.
- **`occupancy_estimates`(재실 추정)** - `rooms/{id}/latest`에서 조회만 가능, 추정값을 넣는 엔드포인트 없음.
- **`control_decisions`(제어 판단)** - 관련 엔드포인트 없음.
- **`simulations`(제어 시뮬레이션)** - 관련 엔드포인트 없음.
- **`operation_sessions`(운영 세션)** - 관련 엔드포인트 없음.

## PWA(Vercel) 배포 - 계속 유지하기로 결정됨, 아직 동작 안 함

`app/`(모바일)는 stlite로 브라우저에서 Python을 직접 돌리는 정적 PWA로 Vercel에 배포됨 (`scripts/build-pwa.mjs`, `vercel.json`). 이번 DB 연동으로 `app/`이 실제 백엔드 API를 호출하도록 바뀌었는데, PWA 배포 환경에서는 아직 아래 3가지가 막혀있음:

1. **`shared/api_client.py`가 빌드에 안 실림** - `build-pwa.mjs`가 `app/` 폴더만 훑어서 `pwa/`로 복사함. `api_client.py`가 `shared/`로 옮겨졌으므로(이번 리팩터) 빌드 스크립트가 `shared/`도 훑도록 고쳐야 함.
2. **`requests`가 브라우저(Pyodide) 환경에서 그대로 안 돌아감** - stlite의 `mount()` 설정에 `requirements: []`로 비어있어서 `requests` 자체가 설치 안 되고, 설치하더라도 Pyodide 샌드박스에선 일반 소켓 통신이 안 돼서 [`pyodide-http`](https://github.com/koenvo/pyodide-http) 같은 패치가 추가로 필요함.
3. **API가 인터넷에 공개돼 있지 않음** - 지금 API는 로컬 `docker-compose`로만 떠 있음(`127.0.0.1:8000`). Vercel에 배포된 PWA는 방문자 브라우저에서 실행되므로, 방문자 브라우저 기준 `127.0.0.1`이 아니라 **실제로 인터넷에서 접근 가능한 API 주소**가 필요함. → 어디에 배포할지(Railway/Render/Fly.io 등) 팀 결정 필요.

PWA를 다시 살리려면 이 문서 기준으로 순서대로 처리하면 됨.
