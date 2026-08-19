-- =====================================================================
-- ThermoShift 003_indexes.sql  —  인덱스 및 부분 유니크 인덱스
-- 기준: 데이터 정의서 v2.3 / PostgreSQL 15+
-- 실행 순서: 002_tables.sql 다음.
--
-- 참고: sensor_env / sensor_pir / sensor_door / power_readings 의
--       (device_id, measured_at) 조회는 UNIQUE 제약이 만든 인덱스로
--       이미 커버되므로 별도 인덱스를 만들지 않는다.
--       occupancy_estimates(room_id, estimated_at) 도 동일.
-- =====================================================================

-- users — 이메일 부분 유니크 (탈퇴 계정 제외, [v2.3] soft delete 대응)
CREATE UNIQUE INDEX uq_users_email_active
    ON users (email) WHERE deleted_at IS NULL;

-- rooms
CREATE INDEX ix_rooms_owner ON rooms (owner_user_id);

-- devices
CREATE INDEX ix_devices_room      ON devices (room_id);
CREATE INDEX ix_devices_room_type ON devices (room_id, device_type);
CREATE INDEX ix_devices_comm_bad  ON devices (comm_status)
    WHERE comm_status <> 'normal';               -- 장치 이상 목록

-- schedules
CREATE INDEX ix_sched_room_from ON schedules (room_id, valid_from)
    WHERE is_active;                             -- 예약 목록·선냉방 스케줄러

-- control_decisions
CREATE INDEX ix_dec_room_time ON control_decisions (room_id, decided_at DESC);

-- hvac_commands
CREATE INDEX ix_cmd_room_time ON hvac_commands (room_id, issued_at DESC);
CREATE INDEX ix_cmd_pending   ON hvac_commands (command_status)
    WHERE command_status IN ('pending', 'sent'); -- 검증 대기 작업 큐

-- event_logs
CREATE INDEX ix_evt_status_time ON event_logs (status, occurred_at DESC); -- 미확인 우선
CREATE INDEX ix_evt_room_time   ON event_logs (room_id, occurred_at DESC);

-- operation_sessions
CREATE INDEX ix_sess_room_time ON operation_sessions (room_id, started_at DESC);
CREATE UNIQUE INDEX uq_sess_one_active
    ON operation_sessions (room_id) WHERE ended_at IS NULL; -- 진행 중 1개 보장

-- simulations
CREATE INDEX ix_sim_room_time ON simulations (room_id, created_at DESC);