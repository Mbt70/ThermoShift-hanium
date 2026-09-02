# Decision Log

프로젝트 주요 결정을 기록합니다.

| Date | Decision | Reason | Owner |
|---|---|---|---|
| 2026-05-03 | Repository baseline 문서 구조 생성 | 팀 협업과 개발 시작을 빠르게 하기 위해 | Jongmin |
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
