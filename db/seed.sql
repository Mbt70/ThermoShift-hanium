-- =====================================================================
-- ThermoShift seed.sql  —  개발용 최소 더미 데이터
-- 기준: v2.3 / PostgreSQL 15+
-- 실행 순서: 003_indexes.sql 다음 (파일명 알파벳순으로 마지막).
--
-- 목적: mock 을 뗀 뒤에도 프론트 전 화면이 비지 않도록 최소 데이터 제공.
-- 주의: password_hash 는 개발용 더미 값이다 (실제 해시 아님).
-- =====================================================================

-- 1) 사용자 1명
INSERT INTO users (name, email, password_hash, is_demo)
VALUES ('테스트관리자', 'admin@thermoshift.dev', 'dev-dummy-hash-not-real', true);

-- 2) 공간 1개 (소유자 = 위 사용자)
INSERT INTO rooms (owner_user_id, name, location, control_mode,
                   target_temp, temp_tolerance, co2_limit, humidity_min, humidity_max)
SELECT user_id, '공학관 401호', '공학관 4층', 'monitoring',
       24.0, 1.0, 1000, 40.0, 60.0
FROM users WHERE email = 'admin@thermoshift.dev';

-- 3) 장치 5개 (env / pir / door / ir / plug)
--    device_uid 는 예시 MAC (대문자·숫자). 실제 값은 하드웨어팀 확인 후 교체.
INSERT INTO devices (room_id, device_code, device_uid, device_type, install_location, comm_status)
SELECT r.room_id, v.code, v.uid, v.dtype::device_type, v.loc, 'normal'
FROM rooms r,
     (VALUES
        ('env_01',  'A0B765000001', 'env',  '천장 중앙'),
        ('pir_01',  'A0B765000002', 'pir',  '출입문 상단'),
        ('door_01', 'A0B765000003', 'door', '출입문 프레임'),
        ('ir_01',   'A0B765000004', 'ir',   '에어컨 정면'),
        ('plug_01', 'A0B765000005', 'plug', '에어컨 콘센트')
     ) AS v(code, uid, dtype, loc)
WHERE r.name = '공학관 401호';

-- 4) 환경 센서 시계열 — 최근 30분, 1분 간격 (그래프용)
INSERT INTO sensor_env (device_id, temperature, humidity, co2, measured_at, received_at)
SELECT d.device_id,
       (24 + (random() * 4 - 2))::numeric(4,1),
       (50 + (random() * 10 - 5))::numeric(4,1),
       (600 + random() * 400)::int,
       ts,
       ts + interval '1 second'
FROM (SELECT device_id FROM devices WHERE device_code = 'env_01') d
CROSS JOIN generate_series(now() - interval '30 minutes', now(), interval '1 minute') AS ts;

-- 5) 전력 시계열 — 최근 30분, 1분 간격 (앞 15분 냉방 ON ≈ 1kW, 이후 OFF)
INSERT INTO power_readings (device_id, power_w, measured_at, received_at)
SELECT d.device_id,
       CASE WHEN ts < now() - interval '15 minutes'
            THEN (950 + random() * 150)::numeric(10,2)
            ELSE (2 + random() * 5)::numeric(10,2) END,
       ts,
       ts + interval '1 second'
FROM (SELECT device_id FROM devices WHERE device_code = 'plug_01') d
CROSS JOIN generate_series(now() - interval '30 minutes', now(), interval '1 minute') AS ts;

-- 6) PIR / 문센서 각 1행 (재실 화면용)
INSERT INTO sensor_pir (device_id, motion, measured_at, received_at)
SELECT device_id, true, now() - interval '2 minutes', now() - interval '2 minutes'
FROM devices WHERE device_code = 'pir_01';

INSERT INTO sensor_door (device_id, door_state, measured_at, received_at)
SELECT device_id, 'closed', now() - interval '10 minutes', now() - interval '10 minutes'
FROM devices WHERE device_code = 'door_01';

-- 7) 예약 1건 (예약 화면용) — 평일 09:00~11:00 반복
INSERT INTO schedules (room_id, created_by, title, valid_from, valid_until,
                       start_time, end_time, repeat_days, target_temp, precooling_min)
SELECT r.room_id, u.user_id, '자료구조 강의', CURRENT_DATE, CURRENT_DATE + 90,
       '09:00', '11:00', ARRAY[1,2,3,4,5]::smallint[], 23.0, 15
FROM rooms r, users u
WHERE r.name = '공학관 401호' AND u.email = 'admin@thermoshift.dev';

-- 8) 재실 추정 1행 (대시보드 현재 재실)
INSERT INTO occupancy_estimates (room_id, occupancy_state, estimated_count,
                                 probability, evidence_summary, estimated_at)
SELECT room_id, 'occupied', 12, 0.870,
       '최근 5분 PIR 7회, 문 개폐 2회, CO2 680→790 ppm 상승', now() - interval '1 minute'
FROM rooms WHERE name = '공학관 401호';

-- 9) 제어 판단 1행 (제어 로그 화면)
INSERT INTO control_decisions (room_id, estimate_id, control_mode, decision_type,
                               target_temp, reason, decided_at)
SELECT r.room_id, e.estimate_id, 'rule', 'maintain', 24.0,
       '재실 감지 + CO2 상승으로 현행 냉방 유지', now() - interval '1 minute'
FROM rooms r
JOIN occupancy_estimates e ON e.room_id = r.room_id
WHERE r.name = '공학관 401호';

-- 10) HVAC 명령 1행 (제어 이력 화면, 검증 성공 케이스)
INSERT INTO hvac_commands (room_id, device_id, decision_id, command_type, control_mode,
                           target_temp, command_status, issued_at,
                           power_before_w, power_after_w, verify_result,
                           result_message, verified_at)
SELECT r.room_id, d.device_id, dec.decision_id, 'power_on', 'rule',
       24.0, 'acked', now() - interval '3 minutes',
       3.0, 1010.0, 'success', '전력 3W→1010W 상승으로 냉방 가동 확인',
       now() - interval '1 minute'
FROM rooms r
JOIN devices d ON d.room_id = r.room_id AND d.device_code = 'ir_01'
JOIN control_decisions dec ON dec.room_id = r.room_id
WHERE r.name = '공학관 401호';

-- 11) 실증 운영 구간 1개 (진행 중)
INSERT INTO operation_sessions (room_id, mode, started_at, target_temp, description)
SELECT room_id, 'rule', now() - interval '1 hour', 24.0, '규칙 제어 실증 진행 중'
FROM rooms WHERE name = '공학관 401호';

-- 12) 이벤트 1건 (알림 화면)
INSERT INTO event_logs (room_id, event_category, event_severity, status, message, occurred_at)
SELECT room_id, 'co2_exceed', 'warning', 'open',
       'CO2 1050ppm 로 기준(1000) 초과 — 환기 권장', now() - interval '5 minutes'
FROM rooms WHERE name = '공학관 401호';
