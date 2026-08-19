# ThermoShift API

프론트엔드(Streamlit)와 게이트웨이(제어 두뇌) 사이의 데이터·제어 API입니다.

## 역할 경계

이 서비스는 **제어 판단을 하지 않습니다.** 냉방을 켤지 끌지 결정하는 것은
`gateway/`(구 thermoshift-edge)의 몫입니다. 제어 명령이 두 곳에서 나가면
에어컨이 서로 반대로 조작되기 때문에, 역할을 다음과 같이 못 박았습니다.

| | gateway | api |
|---|---|---|
| MQTT 구독 | O | X |
| 재실 추정(HMM) | O | X |
| 제어 판단·IR 송신 | O | X |
| SQLite 쓰기 | 센서/재실/제어 로그 | 공간·디바이스·사용자·예약·명령 큐 |
| HTTP 제공 | X | O |

사용자가 프론트에서 수동 제어를 누르면 API는 `control_commands` 테이블에
`pending` 명령을 넣기만 하고, 실제 IR 송신은 gateway가 가져가서 수행합니다.

## 실행

```bash
python3 -m venv .venv
.venv/bin/pip install -r api/requirements.txt

# DB 준비 (반복 실행해도 안전)
python3 db/migrate.py

.venv/bin/python -m uvicorn api.app.main:app --host 0.0.0.0 --port 8100
```

문서화된 스펙은 서버를 띄운 뒤 <http://localhost:8100/docs> 에서 볼 수 있습니다.

## 환경변수

| 변수 | 기본값 | 설명 |
|---|---|---|
| `THERMOSHIFT_DB` | `/home/thermo/thermoshift-data/thermoshift.db` | 통합 SQLite 경로 |
| `THERMOSHIFT_TZ` | `Asia/Seoul` | 응답에 쓰는 로컬 시간대 |
| `THERMOSHIFT_ALLOWED_ORIGINS` | `*` | CORS 허용 출처 (실증 환경에서는 좁힐 것) |
| `THERMOSHIFT_LOG_LEVEL` | `INFO` | 로그 레벨 |

## 엔드포인트

### 인증
| 메서드 | 경로 | 설명 |
|---|---|---|
| POST | `/api/auth/register` | 가입. 중복이면 409 |
| POST | `/api/auth/login` | 로그인. 실패는 401 |
| GET | `/api/auth/users/{email}` | 조회 |
| PATCH | `/api/auth/users/{email}` | 이름·비밀번호 변경 |
| DELETE | `/api/auth/users/{email}` | 탈퇴 |

비밀번호는 PBKDF2-HMAC-SHA256(260k회)로 해싱해 저장합니다. 평문을 보관하지 않습니다.

### 공간
| 메서드 | 경로 | 설명 |
|---|---|---|
| GET | `/api/rooms?owner_email=` | 목록. 실시간 측정값이 합쳐져 나옴 |
| POST | `/api/rooms` | 등록 |
| GET | `/api/rooms/{id}` | 단건 |
| PATCH | `/api/rooms/{id}` | 이름·목표온도·제어모드 변경 |
| DELETE | `/api/rooms/{id}` | 삭제 |
| GET | `/api/rooms/{id}/trend?metric=&hours=&points=` | 다운샘플링된 시계열 |
| GET | `/api/rooms/{id}/devices` | 배정된 디바이스 |

공간 응답에는 `temperature` / `humidity` / `co2` / `occupied` / `aircon_on` /
`sensor_connected` 가 포함됩니다. 측정 이력이 없으면 `null` 이므로 프론트는
`None` 을 처리할 수 있어야 합니다.

### 디바이스
| 메서드 | 경로 | 설명 |
|---|---|---|
| GET | `/api/devices?room_id=&unassigned=` | 목록 |
| PATCH | `/api/devices/{id}` | 공간 배정, 타입·위치·사용여부 변경 |

MQTT에서 처음 보는 `device_id` 는 `room_id = NULL` 인 미배정 상태로 등록되고,
사용자가 화면에서 공간에 배정합니다.

### 제어
| 메서드 | 경로 | 설명 |
|---|---|---|
| GET | `/api/control/logs?room_id=&date=&method=` | 제어 로그 (자동 판단 + 수동 명령 통합) |
| GET | `/api/control/logs/{log_id}` | 단건 |
| POST | `/api/control/commands?room_id=` | 수동 명령을 큐에 등록 |
| GET | `/api/control/commands?status=pending` | gateway가 가져갈 큐 |
| PATCH | `/api/control/commands/{id}` | gateway가 실행 결과 보고 |

자동 판단은 30초마다 쌓이므로 **액션이 바뀐 지점만** 로그로 노출합니다.
같은 판단이 하루 종일 이어졌다면 그날 로그는 비어 있는 것이 정상입니다.

### 알림
| 메서드 | 경로 | 설명 |
|---|---|---|
| GET | `/api/alerts?room_id=&status=&type=` | 목록. 조회 시점에 규칙을 재평가 |
| GET | `/api/alerts/summary?room_id=` | 활성 건수와 심각도별 집계 |
| POST | `/api/alerts/{id}/read` | 읽음 처리 |

알림 ID는 `{room_id}:{type}:{device_id}` 로 결정적으로 만들어져, 같은 원인이
반복돼도 중복 생성되지 않습니다. 조건이 풀리면 `resolved` 로 내려갑니다.

### 예약
| 메서드 | 경로 | 설명 |
|---|---|---|
| GET | `/api/schedules?room_id=&today_only=` | 목록 |
| POST | `/api/schedules?room_id=` | 등록 |
| GET/PUT/DELETE | `/api/schedules/{id}` | 단건 조회·수정·삭제 |

### 상태
| 메서드 | 경로 | 설명 |
|---|---|---|
| GET | `/api/health` | DB 경로, 테이블별 행 수, 마지막 센서 수신 시각 |

## 시간대 규칙

- **저장은 UTC**, **응답은 로컬 시간대 ISO(offset 포함)** 입니다.
- 프론트는 받은 문자열을 `datetime.fromisoformat` 한 뒤 tz 정보를 떼고 씁니다.
- 이 규칙은 `api/app/services/timeutil.py` 한 곳에 모여 있습니다.
