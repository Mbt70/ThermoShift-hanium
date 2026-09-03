# ThermoShift Gateway

ThermoShift 제어 두뇌입니다. (구 `thermoshift-edge`)

MQTT로 센서를 받아 재실을 추정하고 냉방 제어를 판단합니다.
**제어 명령은 이 프로세스에서만 나갑니다** — 자세한 역할 경계는
[`docs/architecture.md`](../docs/architecture.md) 참고.

## 시스템 구성
- MQTT Broker를 통한 센서/제어 데이터 통신
- SQLite 기반 경량 로그 (센서 측정값, 재실 확률, 제어 판단 등 저장)
- HMM 기반 재실 상태 추정기
- 규칙 기반 냉방 제어기
- 외부 리모컨 수동 조작 보호

## 감지 장치별 역할
- env01 (SHT31, SCD41): 온도, 습도, CO2 측정
- occ01 (PIR, 문): 움직임 및 출입 이벤트 감지
- ir01 (IR 송수신): 에어컨 제어 명령 송신 및 외부 리모컨 신호 수신

## MQTT 토픽과 Payload
- Topic: `thermoshift/#`, `esp32/device/#`
- Payload는 각 장비별로 다소 혼재되어 있으나, `MQTTAdapter`에서 `device_id`, `temperature`, `humidity`, `co2`, `motion`, `door_open`, `code_hash` 등을 표준화하여 사용합니다.

## 설치 및 실행 방법
1. 저장소 루트에서 가상 환경 생성 및 패키지 설치:
   ```bash
   python3 -m venv .venv
   .venv/bin/pip install -r gateway/requirements.txt
   ```
2. 설정 파일 복사:
   ```bash
   cp gateway/config/config.example.yaml gateway/config/config.yaml
   ```
3. DB 준비 및 서비스 설치 (api·web과 함께 등록):
   ```bash
   python3 db/migrate.py
   bash infra/systemd/install.sh
   ```

## 설정값
`config/config.yaml` 참조
- 제어 최소 유지 시간, 설정 온도, CO2 경고 수치 등 조정 가능.

## 모드 차이
- **shadow**: 실제 IR 제어 신호를 보내지 않고 데이터만 로깅합니다. (기본값)
- **active**: 제어 명령이 발생할 때마다 IR로 전송합니다.

## 수동조작 Lockout
- 외부에서 리모컨으로 조작된 신호가 IR 수신기에 감지되면 설정된 시간(기본 30분) 동안 자동 제어가 차단됩니다.

## DB 구조
PostgreSQL. api 와 같은 데이터베이스를 봅니다. 접속 정보는 환경변수로
줍니다 (`DB_HOST` `DB_PORT` `DB_USER` `DB_PASSWORD` `DB_NAME`).

스키마 정의는 `db/001_types.sql` ~ `db/003_indexs.sql` 이 원본이고,
게이트웨이만 쓰는 것은 `db/004_gateway.sql` 에 따로 있습니다.

게이트웨이가 쓰는 표
- `sensor_env` / `sensor_pir` / `sensor_door` — 센서 측정 원본
- `occupancy_estimates` — HMM 재실 추정
- `control_decisions` — 제어 판단 (`estimate_id` 로 위 추정을 가리킵니다)
- `hvac_commands` — 프론트에서 들어온 수동 명령 큐. 여기서 소비합니다
- `event_logs` — 시스템 이벤트
- `ir_events` — IR 송수신 기록 (004)

온·습도·CO2 는 `sensor_env` 한 행에 함께 담깁니다. 게이트웨이는 metric
별로 따로 넣으므로 `(device_id, measured_at)` UPSERT 로 합칩니다.

디바이스는 `device_uid` 로 식별합니다. CHECK 제약이 대문자·숫자만
허용해서 `env_01` 은 `ENV01` 로 정규화되고, 원래 이름은 `device_code` 에
남습니다.

### 오프라인 버퍼

PostgreSQL은 EC2에 있고 게이트웨이(파이)는 Tailscale 사설망 너머로
접속합니다. 그 구간이 끊기면 쓰기 메서드(`storage.py`의 insert_*)는
예외 대신 `gateway/app/local_buffer.py`(SQLite, `gateway/data/buffer.sqlite3`)에
쌓아 두고, 연결이 돌아오면 매 제어 주기 `storage.flush_pending()`이
순서대로 다시 밀어 넣습니다. 자세한 배경은
[`docs/decision-log.md`](../docs/decision-log.md) 2026-09-02 항목 참고.

## CLI 도구
```bash
cd gateway && ../.venv/bin/python -m app.cli status
```
상태 조회 기능을 통해 현재 측정값 및 제어 판단을 확인할 수 있습니다.

## 다중 공간에 대해

스키마는 여러 공간을 지원하지만, 이 프로세스는 아직 **단일 공간 전제**입니다.
HMM·controller·feature engine이 전역 싱글톤이라 공간이 여러 개여도 하나로
취급합니다. 담당 공간은 `app.room_id` 설정으로 지정하거나, 비워 두면
`devices` 테이블에서 배정된 공간을 자동으로 따릅니다.

## 현재 한계
- 외기온 없음
- 전력 피드백 없음
- 실제 에어컨 상태 검증 불가
- HMM 파라미터는 초기값이며 실증 데이터로 보정 필요
- MPC는 RC 모델 기반 시뮬레이션 최적화를 수행하지만, 현장 교정 전에는 결과를
  성능 실증값으로 사용하지 않음
- CO₂ 질량보존 + 1차원 Kalman 추정기는 실제 공간용 옵션이며, 12 L 히터 목업에서는
  기본 비활성화
