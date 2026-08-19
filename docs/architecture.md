# Architecture

> 2026-08-19 갱신. 이전 문서는 기술 스택 후보만 나열한 초안이었고, 이 문서는
> 실제로 라즈베리파이에서 동작하는 구조를 기록한 것입니다.

## 전체 구조

```text
  ESP32 노드 (env_01 / occ_01 / ir_01)
        │  MQTT (thermoshift/<device_id>/status)
        ▼
  Mosquitto  :1883
        │
        ▼
  gateway/            ← 제어 두뇌 (Python 프로세스)
    · MQTT 구독, 데이터 품질 검사
    · HMM 재실 추정 (EMPTY / TRANSITION / OCCUPIED)
    · rule 기반 냉방 제어 판단
    · IR 송신, 외부 리모컨 감지 시 수동조작 lockout
    · 프론트가 넣은 수동 명령 큐 소비
        │  SQLite 쓰기
        ▼
  /home/thermo/thermoshift-data/thermoshift.db   ← 단일 진실원(SSOT)
        │  SQLite 읽기 + 메타데이터 쓰기
        ▼
  api/                ← FastAPI :8100
    · 센서/재실/제어 로그를 프론트 형태로 가공
    · 공간·디바이스·사용자·예약 CRUD
    · 수동 제어 명령을 큐에 등록
    · 알림 규칙 평가
        │  HTTP (JSON)
        ▼
  app/ · web/         ← Streamlit :8501
    · app/  모바일 화면
    · web/  데스크톱 대시보드
    · 두 앱이 app/components/*_store.py 를 공용 데이터 계층으로 공유
```

## 역할 경계 — 왜 이렇게 나눴는가

가장 중요한 규칙은 **제어 명령은 gateway에서만 나간다**는 것입니다.

통합 전에는 `thermoshift/backend`(FastAPI)와 `thermoshift-edge`가 **둘 다**
MQTT를 구독하고 **둘 다** 제어 상태를 들고 있었습니다. 이 상태로 두 프로세스가
동시에 동작하면 한쪽은 냉방을 켜고 다른 쪽은 끄는 상황이 생깁니다.

그래서 다음과 같이 분리했습니다.

| | gateway | api |
|---|---|---|
| MQTT 구독 | O | X |
| 재실 추정(HMM) | O | X |
| 제어 판단 · IR 송신 | O | X |
| SQLite 쓰기 | 센서·재실·제어 로그 | 공간·디바이스·사용자·예약·명령 큐 |
| HTTP 제공 | X | O |

사용자가 화면에서 수동 제어를 누르면 API는 `control_commands` 테이블에
`pending` 으로 넣기만 합니다. 실제 IR 송신은 gateway가 큐를 집어가서 수행하고,
결과를 `sent` / `failed` 로 되돌려 씁니다.

## 데이터 저장소

**SQLite 하나로 통일했습니다.** (이전에는 InfluxDB와 SQLite에 이원화)

- baseline 대비 KPI 비교는 SQL window/join으로 쓰는 편이 압도적으로 편합니다.
- 라즈베리파이에서 InfluxDB는 메모리 부담이 있고 백업·복구가 번거롭습니다.
- 데모 규모(공간 2~5개, 30초 주기)면 SQLite로 수년치를 감당합니다.

스키마는 `db/schema/schema.sql` 한 곳에서만 관리하고, gateway와 api가 같은
파일을 적용합니다. 기존 DB에 컬럼을 덧붙이는 마이그레이션은 `db/migrate.py`
가 담당합니다(반복 실행해도 안전).

### 측정값과 공간의 연결

`sensor_readings` 는 `device_id` 만 들고 있고, 공간 귀속은 `devices.room_id`
조인으로 해결합니다. 디바이스를 다른 공간으로 옮기면 과거 데이터도 함께
따라갑니다.

MQTT에서 처음 보는 `device_id` 는 `room_id = NULL` 인 **미배정** 상태로 자동
등록되고, 사용자가 프론트의 공간·디바이스 화면에서 공간에 배정합니다.

## 시간대 규칙

- **저장은 항상 UTC**, **API 응답은 로컬 시간대 ISO(offset 포함)**.
- 변환은 `api/app/services/timeutil.py` 한 곳에만 있습니다.
- 프론트는 받은 문자열을 `fromisoformat` 한 뒤 tz 정보를 떼고 사용합니다.

## 프론트엔드 연결 방식

프론트는 페이지가 store 함수만 호출하는 구조라, **store 내부만 API 호출로
교체**하면 화면 코드는 건드릴 필요가 없었습니다.

`app/components/backend.py` 가 얇은 HTTP 래퍼이고, 각 store 함수는

1. `THERMOSHIFT_API_BASE` 가 설정돼 있으면 API를 호출하고,
2. API가 꺼져 있거나 오류면 기존 로컬 JSON 목데이터로 폴백합니다.

덕분에 파이에서는 실데이터로, 팀원 노트북에서는 백엔드 없이도 프론트를 그대로
띄울 수 있습니다. 연속 3회 실패하면 그 프로세스에서는 API 호출을 잠시 꺼서
Streamlit이 rerun할 때마다 타임아웃을 기다리지 않도록 했습니다.

## 실행

```bash
# 1) 의존성
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt -r api/requirements.txt -r gateway/requirements.txt

# 2) DB
python3 db/migrate.py

# 3) 게이트웨이 설정
cp gateway/config/config.example.yaml gateway/config/config.yaml

# 4) 서비스 등록 (라즈베리파이)
bash infra/systemd/install.sh
```

개발 중에는 각각 따로 띄워도 됩니다.

```bash
cd gateway && ../.venv/bin/python -m app.main
.venv/bin/python -m uvicorn api.app.main:app --port 8100
THERMOSHIFT_API_BASE=http://127.0.0.1:8100 .venv/bin/python -m streamlit run web/main.py
```

## 아직 남은 것

- **gateway가 단일 공간 전제**입니다. HMM·controller·feature engine이 전역
  싱글톤이라 공간이 여러 개여도 하나로 취급합니다. 스키마는 다중 공간을
  지원하므로, 공간별 인스턴스로 나누는 작업만 남았습니다.
- **전력 실측이 없습니다.** 스마트 플러그(plug 타입 디바이스)가 붙기 전까지
  `api/app/services/snapshot.py` 의 `estimate_power_kw()` 가 추정값을 냅니다.
  KPI의 "에너지 사용량"은 실측이 들어와야 의미가 생깁니다.
- **외기온 연동이 없습니다.** pre-cooling 판단 고도화에 필요합니다.
- **IR 코드가 placeholder** 입니다. `gateway/config/config.yaml` 의
  `ir.codes` 를 실제 학습값으로 채우기 전에는 active 모드로 올릴 수 없습니다
  (CLI가 placeholder를 감지하면 active 전환을 거부합니다).
