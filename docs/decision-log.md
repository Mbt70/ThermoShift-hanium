# Decision Log

프로젝트 주요 결정을 기록합니다.

| Date | Decision | Reason | Owner |
|---|---|---|---|
| 2026-05-03 | Repository baseline 문서 구조 생성 | 팀 협업과 개발 시작을 빠르게 하기 위해 | Jongmin |
| 2026-08-19 | 데이터 저장소를 SQLite로 단일화 | KPI 비교 쿼리 편의 · 파이 리소스 · 백업 단순화 | Jongmin |
| 2026-08-19 | 흩어진 3개 저장소를 hanium 모노레포로 통합 | 팀원이 한 곳에서 PR을 주고받고 버전 어긋남을 없애기 위해 | Jongmin |
| 2026-08-19 | 제어 명령 발신을 gateway 한 곳으로 제한 | backend와 edge가 둘 다 제어해 충돌하는 것을 막기 위해 | Jongmin |

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

### 2026-08-19 - 데이터 저장소를 SQLite로 단일화

- 결정: 통합 SQLite(`/home/thermo/thermoshift-data/thermoshift.db`)를 단일
  진실원으로 삼는다. InfluxDB는 이관 후 이관 대상에서 제외한다.
- 이유: baseline 대비 KPI 비교는 SQL window/join이 압도적으로 편하다.
  파이에서 InfluxDB는 메모리 부담이 있고 백업·복구가 번거롭다.
  이미 edge가 SQLite에 실데이터 3,094행을 쌓아 둔 상태였다.
- 대안: InfluxDB 유지 / 둘 다 역할 분리해 유지.
- 영향: 기존 Influx 데이터(2026-07~08 수집분)는 필요하면 CSV로 export해
  보관한다. 스키마는 `db/schema/schema.sql` 한 곳에서 관리한다.
- 담당: Jongmin

### 2026-08-19 - 저장소를 hanium 모노레포로 통합

- 결정: `thermoshift-edge` → `gateway/`, `thermoshift/backend` 역할 → `api/`,
  ESP32 스케치 → `firmware/` 로 옮긴다.
- 이유: 저장소가 3개로 흩어져 있어 팀원이 어디를 clone해야 하는지 알기
  어렵고, API 스키마가 두 곳에 걸쳐 어긋나기 쉬웠다. 한이음 제출도 단일
  저장소가 유리하다.
- 대안: 분리 유지하고 문서로만 연결.
- 영향: 빈 `.gitkeep` 자리(api/ db/ gateway/ firmware/)가 실제 코드로 채워졌다.
  기존 `~/thermoshift`, `~/thermoshift-edge` 는 당장 지우지 않고 백업으로 둔다.
- 담당: Jongmin

### 2026-08-19 - 제어 명령 발신을 gateway 한 곳으로 제한

- 결정: 제어 판단과 IR 송신은 gateway만 수행한다. api는 사용자 명령을
  `control_commands` 큐에 넣기만 한다.
- 이유: 통합 전에는 backend(FastAPI)와 edge가 둘 다 MQTT를 구독하고 둘 다
  제어 상태를 들고 있었다. 두 프로세스가 동시에 돌면 한쪽은 냉방을 켜고
  다른 쪽은 끄는 충돌이 발생한다.
- 대안: api가 직접 MQTT로 제어 명령 발행.
- 영향: 수동 제어는 큐를 거치므로 즉시 반영이 아니라 gateway의 다음 루프
  (기본 30초) 안에 처리된다. shadow 모드에서는 전송하지 않고
  `error_code = shadow_mode` 로 기록해 사용자가 이유를 알 수 있게 했다.
- 담당: Jongmin
