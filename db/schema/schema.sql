-- ThermoShift 통합 스키마 (SQLite)
-- 단일 진실원(SSOT). gateway(제어 두뇌)가 쓰고, api(FastAPI)가 읽습니다.
--
-- 설계 원칙
--  1. 센서/제어 원본 로그는 gateway가 append-only로 적재한다.
--  2. 공간(room)·디바이스·사용자 등 운영 메타데이터는 api가 관리한다.
--  3. 측정값의 공간 귀속은 devices.room_id 조인으로 해결한다
--     (디바이스를 다른 공간으로 옮기면 과거 데이터도 함께 따라간다).

PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

-- ============================================================
-- 운영 메타데이터 (api가 관리)
-- ============================================================

CREATE TABLE IF NOT EXISTS users (
    email         TEXT PRIMARY KEY,
    name          TEXT NOT NULL,
    password_hash TEXT NOT NULL,          -- pbkdf2_sha256$iterations$salt$hash
    created_at    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS rooms (
    id                 TEXT PRIMARY KEY,
    name               TEXT NOT NULL,
    location           TEXT,
    floor_plan_name    TEXT,
    owner_email        TEXT REFERENCES users(email) ON DELETE CASCADE,
    target_temperature REAL    NOT NULL DEFAULT 24.0,
    control_mode       TEXT    NOT NULL DEFAULT 'rule',   -- rule | manual | predict
    auto_control       INTEGER NOT NULL DEFAULT 1,
    created_at         TEXT NOT NULL,
    updated_at         TEXT
);
CREATE INDEX IF NOT EXISTS idx_rooms_owner ON rooms(owner_email);

-- MQTT device_id 가 그대로 PK. gateway가 처음 보는 device_id를 만나면
-- room_id = NULL 인 미배정 상태로 자동 등록되고, 사용자가 공간에 배정한다.
CREATE TABLE IF NOT EXISTS devices (
    id        TEXT PRIMARY KEY,           -- env_01, occ_01, ir_01 ...
    room_id   TEXT REFERENCES rooms(id) ON DELETE SET NULL,
    type      TEXT NOT NULL,              -- env | pir | door | ir | plug
    name      TEXT,
    location  TEXT,
    enabled   INTEGER NOT NULL DEFAULT 1,
    last_seen TEXT
);
CREATE INDEX IF NOT EXISTS idx_devices_room ON devices(room_id);

CREATE TABLE IF NOT EXISTS schedules (
    id                     TEXT PRIMARY KEY,
    room_id                TEXT NOT NULL REFERENCES rooms(id) ON DELETE CASCADE,
    title                  TEXT,
    date                   TEXT NOT NULL,          -- 기준일 YYYY-MM-DD
    start_time             TEXT NOT NULL,          -- HH:MM
    end_time               TEXT NOT NULL,
    target_temperature     REAL    NOT NULL DEFAULT 24.0,
    precool_enabled        INTEGER NOT NULL DEFAULT 0,
    precool_minutes_before INTEGER NOT NULL DEFAULT 20,
    repeat_enabled         INTEGER NOT NULL DEFAULT 0,
    repeat_days            TEXT NOT NULL DEFAULT '[]',  -- JSON: ["mon","tue"]
    created_at             TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_schedules_room ON schedules(room_id);

-- ============================================================
-- 센서/제어 원본 로그 (gateway가 적재)
-- ============================================================

CREATE TABLE IF NOT EXISTS sensor_readings (
    timestamp   TEXT NOT NULL,
    device_id   TEXT NOT NULL,
    metric      TEXT NOT NULL,            -- temperature | humidity | co2 | pir | door | power
    value       REAL,
    quality     TEXT,                     -- OK | INVALID | STALE
    raw_payload TEXT
);
CREATE INDEX IF NOT EXISTS idx_readings_device_ts ON sensor_readings(device_id, timestamp);
CREATE INDEX IF NOT EXISTS idx_readings_metric_ts ON sensor_readings(metric, timestamp);

CREATE TABLE IF NOT EXISTS occupancy_estimates (
    timestamp     TEXT NOT NULL,
    room_id       TEXT REFERENCES rooms(id) ON DELETE CASCADE,
    p_empty       REAL,
    p_transition  REAL,
    p_occupied    REAL,
    state         TEXT,                   -- EMPTY | TRANSITION | OCCUPIED | UNKNOWN
    quality       TEXT,
    reasons_json  TEXT
);
CREATE INDEX IF NOT EXISTS idx_occupancy_room_ts ON occupancy_estimates(room_id, timestamp);

CREATE TABLE IF NOT EXISTS control_decisions (
    timestamp         TEXT NOT NULL,
    room_id           TEXT REFERENCES rooms(id) ON DELETE CASCADE,
    control_mode      TEXT,               -- shadow | active | manual_lockout | failsafe
    proposed_action   TEXT,               -- POWER_OFF | COOL_25_AUTO ...
    executed          BOOLEAN,
    occupancy_state   TEXT,
    temperature_c     REAL,
    co2_ppm           REAL,
    reason_codes_json TEXT
);
CREATE INDEX IF NOT EXISTS idx_decisions_room_ts ON control_decisions(room_id, timestamp);

CREATE TABLE IF NOT EXISTS ir_events (
    timestamp   TEXT NOT NULL,
    room_id     TEXT REFERENCES rooms(id) ON DELETE CASCADE,
    direction   TEXT,                     -- tx | rx
    protocol    TEXT,
    code_hash   TEXT,
    source      TEXT,                     -- auto | manual | unknown
    raw_payload TEXT
);
CREATE INDEX IF NOT EXISTS idx_ir_room_ts ON ir_events(room_id, timestamp);

CREATE TABLE IF NOT EXISTS system_events (
    timestamp  TEXT NOT NULL,
    room_id    TEXT REFERENCES rooms(id) ON DELETE CASCADE,
    severity   TEXT,                      -- INFO | WARNING | CRITICAL
    event_type TEXT,
    message    TEXT
);
CREATE INDEX IF NOT EXISTS idx_events_ts ON system_events(timestamp);

-- ============================================================
-- 사용자 제어 명령 / 알림 (api ↔ gateway 접점)
-- ============================================================

-- 프론트에서 내린 수동 명령. gateway가 status=pending 을 집어가
-- IR로 전송한 뒤 sent/failed 로 갱신한다.
CREATE TABLE IF NOT EXISTS control_commands (
    id          TEXT PRIMARY KEY,
    room_id     TEXT NOT NULL REFERENCES rooms(id) ON DELETE CASCADE,
    created_at  TEXT NOT NULL,
    issued_by   TEXT,                     -- 사용자 email, 자동이면 NULL
    method      TEXT NOT NULL,            -- rule | manual | predict
    action      TEXT NOT NULL,            -- POWER_OFF | COOL_24_AUTO | SET_TARGET ...
    payload_json TEXT,
    status      TEXT NOT NULL DEFAULT 'pending',  -- pending | sent | failed
    error_code  TEXT,                     -- command_failed | no_power_change | ...
    resolved_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_commands_room_ts ON control_commands(room_id, created_at);
CREATE INDEX IF NOT EXISTS idx_commands_status ON control_commands(status);

CREATE TABLE IF NOT EXISTS alerts (
    id         TEXT PRIMARY KEY,
    room_id    TEXT REFERENCES rooms(id) ON DELETE CASCADE,
    device_id  TEXT,
    type       TEXT NOT NULL,             -- sensor_offline | co2_high | temperature_abnormal
                                          -- | control_failed | network_error | humidity_abnormal
                                          -- | door_open | power_abnormal
    severity   TEXT NOT NULL,             -- warning | critical
    title      TEXT NOT NULL,
    message    TEXT,
    created_at TEXT NOT NULL,
    status     TEXT NOT NULL DEFAULT 'active',   -- active | resolved
    read_at    TEXT
);
CREATE INDEX IF NOT EXISTS idx_alerts_room_ts ON alerts(room_id, created_at);
CREATE INDEX IF NOT EXISTS idx_alerts_status ON alerts(status);
