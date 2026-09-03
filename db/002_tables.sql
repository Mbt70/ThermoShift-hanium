-- =====================================================================
-- ThermoShift 002_tables.sql  —  15 테이블 정의
-- 기준: 데이터 정의서 v2.3 / PostgreSQL 15+
-- 실행 순서: 001_types.sql 다음.
--
-- [v2.3 변경분 표시]  각 컬럼 옆 주석에 [v2.3] 로 표기
-- [확인 필요] 표시된 항목은 문서에 명시가 없어 제안값으로 채운 부분
-- [DB 연동] inquiries 테이블은 원래 스키마엔 없었으나, 앱의 1:1 문의 기능을
--          DB 연동하며 추가 (docs/api-status.md 참고)
-- =====================================================================


-- ---------------------------------------------------------------------
-- 1. users — 사용자
-- ---------------------------------------------------------------------
CREATE TABLE users (
    user_id       bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name          varchar(50)  NOT NULL,
    email         varchar(255) NOT NULL,
    password_hash varchar(255) NOT NULL,
    created_at    timestamptz  NOT NULL DEFAULT now(),
    updated_at    timestamptz  NOT NULL DEFAULT now(),
    deleted_at    timestamptz            -- [v2.3] soft delete (NULL=활성)
    -- email UNIQUE 는 부분 유니크 인덱스로 003 에서 정의
    -- (WHERE deleted_at IS NULL — 탈퇴 계정은 이메일 재사용 허용)
);


-- ---------------------------------------------------------------------
-- 2. rooms — 공간
-- ---------------------------------------------------------------------
CREATE TABLE rooms (
    room_id        bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    owner_user_id  bigint       NOT NULL,
    name           varchar(100) NOT NULL,
    location       varchar(200),
    control_mode   control_mode NOT NULL DEFAULT 'monitoring',
    floor_plan_url varchar(500),
    model_3d_url   varchar(500),
    target_temp    numeric(4,1) NOT NULL DEFAULT 24.0,
    temp_tolerance numeric(3,1) NOT NULL DEFAULT 1.0,
    co2_limit      integer      NOT NULL DEFAULT 1000,   -- [v2.3] co2_limit_ppm 에서 개명
    humidity_min   numeric(4,1) NOT NULL DEFAULT 40.0,
    humidity_max   numeric(4,1) NOT NULL DEFAULT 60.0,
    created_at     timestamptz  NOT NULL DEFAULT now(),
    updated_at     timestamptz  NOT NULL DEFAULT now(),
    CONSTRAINT uq_rooms_owner_name UNIQUE (owner_user_id, name),
    CONSTRAINT ck_rooms_target_temp    CHECK (target_temp BETWEEN 16 AND 30),
    CONSTRAINT ck_rooms_temp_tolerance CHECK (temp_tolerance BETWEEN 0 AND 5),
    CONSTRAINT ck_rooms_co2_limit      CHECK (co2_limit BETWEEN 400 AND 5000),
    CONSTRAINT ck_rooms_humidity_min   CHECK (humidity_min BETWEEN 0 AND 100),
    CONSTRAINT ck_rooms_humidity_max   CHECK (humidity_max BETWEEN humidity_min AND 100),
    CONSTRAINT fk_rooms_owner FOREIGN KEY (owner_user_id)
        REFERENCES users (user_id) ON DELETE RESTRICT
);


-- ---------------------------------------------------------------------
-- 3. devices — 디바이스
-- ---------------------------------------------------------------------
CREATE TABLE devices (
    device_id       bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    room_id         bigint       NOT NULL,
    device_code     varchar(30)  NOT NULL,   -- env_01 등 (사람이 보는 이름, 공간 내 유일)
    device_uid      varchar(30)  NOT NULL,   -- [v2.3] MAC 등 기기 고유 ID (전역 유일, 불변)
    device_type     device_type  NOT NULL,
    install_location varchar(100),
    comm_status     comm_status  NOT NULL DEFAULT 'unknown',
    is_enabled      boolean      NOT NULL DEFAULT true,
    twin_x          numeric(6,2),
    twin_y          numeric(6,2),
    twin_z          numeric(6,2),
    last_seen_at    timestamptz,
    created_at      timestamptz  NOT NULL DEFAULT now(),
    updated_at      timestamptz  NOT NULL DEFAULT now(),
    CONSTRAINT uq_devices_room_code UNIQUE (room_id, device_code),
    CONSTRAINT uq_devices_id_type   UNIQUE (device_id, device_type),  -- 타입 정합성 참조용
    CONSTRAINT uq_devices_uid       UNIQUE (device_uid),              -- [v2.3] 전역 유일
    CONSTRAINT ck_devices_uid_format CHECK (device_uid ~ '^[A-Z0-9]+$'), -- [v2.3] 대문자·숫자만
    CONSTRAINT fk_devices_room FOREIGN KEY (room_id)
        REFERENCES rooms (room_id) ON DELETE RESTRICT
);


-- ---------------------------------------------------------------------
-- 4. schedules — 냉방 예약
-- ---------------------------------------------------------------------
CREATE TABLE schedules (
    schedule_id   bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    room_id       bigint       NOT NULL,
    created_by    bigint,
    title         varchar(100),
    valid_from    date         NOT NULL,
    valid_until   date,
    start_time    time         NOT NULL,
    end_time      time         NOT NULL,
    repeat_days   smallint[]   NOT NULL DEFAULT '{}',
    target_temp   numeric(4,1) NOT NULL,
    precooling_min integer     NOT NULL DEFAULT 0,
    is_active     boolean      NOT NULL DEFAULT true,
    created_at    timestamptz  NOT NULL DEFAULT now(),
    updated_at    timestamptz  NOT NULL DEFAULT now(),
    CONSTRAINT ck_sched_time      CHECK (end_time > start_time),
    CONSTRAINT ck_sched_validuntil CHECK (valid_until IS NULL OR valid_until >= valid_from),
    CONSTRAINT ck_sched_target    CHECK (target_temp BETWEEN 16 AND 30),
    CONSTRAINT ck_sched_precool   CHECK (precooling_min BETWEEN 0 AND 180),
    CONSTRAINT ck_sched_days      CHECK (repeat_days <@ ARRAY[1,2,3,4,5,6,7]::smallint[]),
    CONSTRAINT ck_sched_no_infinite CHECK (repeat_days = '{}' OR valid_until IS NOT NULL),
    CONSTRAINT fk_sched_room FOREIGN KEY (room_id)
        REFERENCES rooms (room_id) ON DELETE CASCADE,
    CONSTRAINT fk_sched_creator FOREIGN KEY (created_by)
        REFERENCES users (user_id) ON DELETE SET NULL
);


-- ---------------------------------------------------------------------
-- 5. sensor_env — 온·습도·CO2 측정 (INSERT-only 불변 원본)
-- ---------------------------------------------------------------------
CREATE TABLE sensor_env (
    reading_id    bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    device_id     bigint       NOT NULL,
    -- 소수 두 자리. SCD41 은 0.01℃ 단위로 값을 주는데 numeric(4,1) 로
    -- 받으면 0.1℃ 로 잘려 나간다. 12L 목업에서 재실자 1명 상당(0.36W)이
    -- 30분에 만드는 온도 변화가 약 0.22℃ 라, 0.1℃ 눈금으로는 두 칸밖에
    -- 안 되어 열모델 식별이 불가능했다. 두 자리로 늘리면 같은 실험이
    -- 22칸으로 잡힌다. 설정 온도(target_temp)는 사람이 정하는 값이라
    -- 0.1℃ 로 둔다 — 여기서 바꾸는 것은 '측정값' 뿐이다.
    temperature   numeric(5,2),
    humidity      numeric(5,2),
    co2           integer,
    temp_flag     quality_flag NOT NULL DEFAULT 'ok',  -- [v2.3] 항목별 품질 플래그
    humidity_flag quality_flag NOT NULL DEFAULT 'ok',  -- [v2.3]
    co2_flag      quality_flag NOT NULL DEFAULT 'ok',  -- [v2.3]
    measured_at   timestamptz  NOT NULL,               -- 센서 측정 시각 (기본값 없음)
    received_at   timestamptz  NOT NULL,               -- [v2.3] DB 도착 시각 (FastAPI 기록)
    CONSTRAINT uq_env UNIQUE (device_id, measured_at),
    CONSTRAINT ck_env_temp CHECK (temperature BETWEEN -20 AND 60),
    CONSTRAINT ck_env_humidity CHECK (humidity BETWEEN 0 AND 100),
    CONSTRAINT ck_env_co2 CHECK (co2 BETWEEN 0 AND 10000),
    CONSTRAINT ck_env_notnull CHECK (
        temperature IS NOT NULL OR humidity IS NOT NULL OR co2 IS NOT NULL),
    CONSTRAINT fk_env_device FOREIGN KEY (device_id)
        REFERENCES devices (device_id) ON DELETE RESTRICT
);


-- ---------------------------------------------------------------------
-- 6. sensor_pir — PIR 움직임 측정
-- ---------------------------------------------------------------------
CREATE TABLE sensor_pir (
    pir_reading_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    device_id     bigint       NOT NULL,
    motion        boolean      NOT NULL,
    flag          quality_flag NOT NULL DEFAULT 'ok',  -- [v2.3 / 확인 필요] 단일 품질 플래그
    measured_at   timestamptz  NOT NULL,
    received_at   timestamptz  NOT NULL,               -- [v2.3]
    CONSTRAINT uq_pir UNIQUE (device_id, measured_at),
    CONSTRAINT fk_pir_device FOREIGN KEY (device_id)
        REFERENCES devices (device_id) ON DELETE RESTRICT
);


-- ---------------------------------------------------------------------
-- 7. sensor_door — 문 개폐 측정
-- ---------------------------------------------------------------------
CREATE TABLE sensor_door (
    door_reading_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    device_id     bigint       NOT NULL,
    door_state    door_state   NOT NULL,
    flag          quality_flag NOT NULL DEFAULT 'ok',  -- [v2.3 / 확인 필요]
    measured_at   timestamptz  NOT NULL,
    received_at   timestamptz  NOT NULL,               -- [v2.3]
    CONSTRAINT uq_door UNIQUE (device_id, measured_at),
    CONSTRAINT fk_door_device FOREIGN KEY (device_id)
        REFERENCES devices (device_id) ON DELETE RESTRICT
);


-- ---------------------------------------------------------------------
-- 8. power_readings — 스마트플러그 순간 전력
--    [확인 필요] v2.1 문서에서 컬럼 전체가 노출되지 않아
--    power_w(numeric(10,2)) 는 hvac_commands 스냅샷 타입 기준으로 복원
-- ---------------------------------------------------------------------
CREATE TABLE power_readings (
    power_id      bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    device_id     bigint        NOT NULL,
    power_w       numeric(10,2) NOT NULL,              -- 순간 전력 (W)
    flag          quality_flag  NOT NULL DEFAULT 'ok', -- [v2.3 / 확인 필요]
    measured_at   timestamptz   NOT NULL,
    received_at   timestamptz   NOT NULL,              -- [v2.3]
    CONSTRAINT uq_power UNIQUE (device_id, measured_at),
    CONSTRAINT ck_power_nonneg CHECK (power_w >= 0),
    CONSTRAINT fk_power_device FOREIGN KEY (device_id)
        REFERENCES devices (device_id) ON DELETE RESTRICT
);


-- ---------------------------------------------------------------------
-- 9. occupancy_estimates — 재실 추정
-- ---------------------------------------------------------------------
CREATE TABLE occupancy_estimates (
    estimate_id     bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    room_id         bigint          NOT NULL,
    occupancy_state occupancy_state NOT NULL,
    estimated_count smallint,
    probability     numeric(4,3),
    evidence_summary varchar(500),
    estimated_at    timestamptz     NOT NULL,
    CONSTRAINT uq_occ UNIQUE (room_id, estimated_at),
    CONSTRAINT ck_occ_prob CHECK (probability IS NULL OR probability BETWEEN 0 AND 1),
    CONSTRAINT ck_occ_count CHECK (estimated_count IS NULL OR estimated_count >= 0),
    CONSTRAINT fk_occ_room FOREIGN KEY (room_id)
        REFERENCES rooms (room_id) ON DELETE RESTRICT
);


-- ---------------------------------------------------------------------
-- 10. control_decisions — 제어 판단
-- ---------------------------------------------------------------------
CREATE TABLE control_decisions (
    decision_id   bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    room_id       bigint        NOT NULL,
    estimate_id   bigint,
    schedule_id   bigint,
    control_mode  control_mode  NOT NULL,
    decision_type decision_type NOT NULL,
    target_temp   numeric(4,1),
    reason        text,
    decided_at    timestamptz   NOT NULL,
    CONSTRAINT ck_dec_target CHECK (target_temp IS NULL OR target_temp BETWEEN 16 AND 30),
    CONSTRAINT fk_dec_room FOREIGN KEY (room_id)
        REFERENCES rooms (room_id) ON DELETE RESTRICT,
    CONSTRAINT fk_dec_estimate FOREIGN KEY (estimate_id)
        REFERENCES occupancy_estimates (estimate_id) ON DELETE SET NULL,
    CONSTRAINT fk_dec_schedule FOREIGN KEY (schedule_id)
        REFERENCES schedules (schedule_id) ON DELETE SET NULL
);


-- ---------------------------------------------------------------------
-- 11. hvac_commands — HVAC 명령 및 최종 검증
-- ---------------------------------------------------------------------
CREATE TABLE hvac_commands (
    command_id      bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    room_id         bigint         NOT NULL,
    device_id       bigint         NOT NULL,   -- IR 송신기 (device_type='ir')
    decision_id     bigint,
    schedule_id     bigint,
    issued_by       bigint,
    command_type    command_type   NOT NULL,
    control_mode    control_mode   NOT NULL,
    target_temp     numeric(4,1),
    command_status  command_status NOT NULL DEFAULT 'pending',
    payload         jsonb,
    issued_at       timestamptz    NOT NULL DEFAULT now(),
    power_before_id bigint,
    power_after_id  bigint,
    power_before_w  numeric(10,2),
    power_after_w   numeric(10,2),
    verify_result   verify_result,
    result_message  varchar(500),
    estimated_cause varchar(300),
    action_guide    varchar(300),
    verified_at     timestamptz,
    CONSTRAINT ck_cmd_target CHECK (target_temp IS NULL OR target_temp BETWEEN 16 AND 30),
    CONSTRAINT ck_cmd_verify_pair CHECK ((verify_result IS NULL) = (verified_at IS NULL)),
    CONSTRAINT ck_cmd_acked CHECK (command_status <> 'acked' OR verify_result = 'success'),
    CONSTRAINT fk_cmd_room FOREIGN KEY (room_id)
        REFERENCES rooms (room_id) ON DELETE RESTRICT,
    CONSTRAINT fk_cmd_device FOREIGN KEY (device_id)
        REFERENCES devices (device_id) ON DELETE RESTRICT,
    CONSTRAINT fk_cmd_decision FOREIGN KEY (decision_id)
        REFERENCES control_decisions (decision_id) ON DELETE SET NULL,
    CONSTRAINT fk_cmd_schedule FOREIGN KEY (schedule_id)
        REFERENCES schedules (schedule_id) ON DELETE SET NULL,
    CONSTRAINT fk_cmd_issuer FOREIGN KEY (issued_by)
        REFERENCES users (user_id) ON DELETE SET NULL,
    CONSTRAINT fk_cmd_power_before FOREIGN KEY (power_before_id)
        REFERENCES power_readings (power_id) ON DELETE SET NULL,
    CONSTRAINT fk_cmd_power_after FOREIGN KEY (power_after_id)
        REFERENCES power_readings (power_id) ON DELETE SET NULL
);


-- ---------------------------------------------------------------------
-- 12. event_logs — 이벤트·알림
--    [확인 필요] v2.1 문서에서 컬럼 전체가 노출되지 않아
--    인덱스/요약 기준(occurred_at·read_at·resolved_at·status)으로 복원
-- ---------------------------------------------------------------------
CREATE TABLE event_logs (
    event_id       bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    room_id        bigint,
    device_id      bigint,
    command_id     bigint,
    event_category event_category NOT NULL,
    event_severity event_severity NOT NULL,
    status         event_status   NOT NULL DEFAULT 'open',
    message        varchar(500),
    occurred_at    timestamptz    NOT NULL DEFAULT now(),
    read_at        timestamptz,
    resolved_at    timestamptz,
    CONSTRAINT fk_evt_room FOREIGN KEY (room_id)
        REFERENCES rooms (room_id) ON DELETE SET NULL,
    CONSTRAINT fk_evt_device FOREIGN KEY (device_id)
        REFERENCES devices (device_id) ON DELETE SET NULL,
    CONSTRAINT fk_evt_command FOREIGN KEY (command_id)
        REFERENCES hvac_commands (command_id) ON DELETE SET NULL
);


-- ---------------------------------------------------------------------
-- 13. operation_sessions — 실증 운영 구간
-- ---------------------------------------------------------------------
CREATE TABLE operation_sessions (
    session_id  bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    room_id     bigint         NOT NULL,
    mode        operation_mode NOT NULL,
    started_at  timestamptz    NOT NULL,
    ended_at    timestamptz,                 -- NULL = 진행 중
    target_temp numeric(4,1),
    description varchar(500),
    created_at  timestamptz    NOT NULL DEFAULT now(),
    CONSTRAINT ck_sess_time CHECK (ended_at IS NULL OR ended_at > started_at),
    CONSTRAINT fk_sess_room FOREIGN KEY (room_id)
        REFERENCES rooms (room_id) ON DELETE RESTRICT
    -- "진행 중 구간 최대 1개" 부분 유니크 인덱스는 003 에서 정의
);


-- ---------------------------------------------------------------------
-- 14. simulations — 제어 시뮬레이션
-- ---------------------------------------------------------------------
CREATE TABLE simulations (
    sim_id             bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    room_id            bigint         NOT NULL,
    created_by         bigint,
    period_start       timestamptz    NOT NULL,
    period_end         timestamptz    NOT NULL,
    expected_occupancy integer,
    target_temp        numeric(4,1)   NOT NULL,
    outdoor_temp       numeric(4,1),
    ventilation_available boolean     NOT NULL DEFAULT true,
    results            jsonb          NOT NULL,
    recommend_mode     operation_mode,
    reason             text,
    created_at         timestamptz    NOT NULL DEFAULT now(),
    CONSTRAINT ck_sim_period CHECK (period_end > period_start),
    CONSTRAINT ck_sim_target CHECK (target_temp BETWEEN 16 AND 30),
    CONSTRAINT ck_sim_occ CHECK (expected_occupancy IS NULL OR expected_occupancy >= 0),
    CONSTRAINT fk_sim_room FOREIGN KEY (room_id)
        REFERENCES rooms (room_id) ON DELETE CASCADE,
    CONSTRAINT fk_sim_creator FOREIGN KEY (created_by)
        REFERENCES users (user_id) ON DELETE SET NULL
);


-- ---------------------------------------------------------------------
-- 15. inquiries — 1:1 문의 (앱 제어 로그 상세에서 접수)
-- ---------------------------------------------------------------------
CREATE TABLE inquiries (
    inquiry_id  bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    room_id     bigint        NOT NULL,
    command_id  bigint,                    -- 어떤 제어 로그(hvac_commands)에 대한 문의인지, 없을 수도 있음
    user_id     bigint,                    -- 문의한 사용자, 탈퇴 시 NULL로 남김
    message     varchar(1000) NOT NULL,
    created_at  timestamptz   NOT NULL DEFAULT now(),
    CONSTRAINT ck_inquiries_message CHECK (length(trim(message)) > 0),
    CONSTRAINT fk_inquiries_room FOREIGN KEY (room_id)
        REFERENCES rooms (room_id) ON DELETE CASCADE,
    CONSTRAINT fk_inquiries_command FOREIGN KEY (command_id)
        REFERENCES hvac_commands (command_id) ON DELETE SET NULL,
    CONSTRAINT fk_inquiries_user FOREIGN KEY (user_id)
        REFERENCES users (user_id) ON DELETE SET NULL
);


-- =====================================================================
-- updated_at 자동 갱신 트리거 (마스터 테이블 4개)
-- =====================================================================
CREATE OR REPLACE FUNCTION set_updated_at()
RETURNS trigger AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_users_updated    BEFORE UPDATE ON users
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE TRIGGER trg_rooms_updated    BEFORE UPDATE ON rooms
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE TRIGGER trg_devices_updated  BEFORE UPDATE ON devices
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE TRIGGER trg_sched_updated    BEFORE UPDATE ON schedules
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();