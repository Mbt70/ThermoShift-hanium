-- =====================================================================
-- ThermoShift 001_types.sql  —  ENUM 타입 정의
-- 기준: 데이터 정의서 v2.3 (14 테이블) / PostgreSQL 15+
-- 이 파일은 테이블보다 먼저 실행되어야 한다 (테이블이 ENUM을 참조).
-- =====================================================================

-- 장치 유형
CREATE TYPE device_type AS ENUM ('env', 'pir', 'door', 'ir', 'plug');

-- 장치 통신 상태
CREATE TYPE comm_status AS ENUM ('normal', 'offline', 'error', 'unknown');

-- 문 상태
CREATE TYPE door_state AS ENUM ('open', 'closed');

-- 재실 상태
CREATE TYPE occupancy_state AS ENUM ('empty', 'transition', 'occupied', 'unknown');

-- 제어 모드 (UI "예측 제어" = DB 'mpc')
CREATE TYPE control_mode AS ENUM ('monitoring', 'manual', 'rule', 'mpc');

-- 제어 판단 유형
CREATE TYPE decision_type AS ENUM ('precool', 'maintain', 'setback', 'ventilate', 'off');

-- 명령 종류
CREATE TYPE command_type AS ENUM ('power_on', 'power_off', 'set_temp', 'set_mode', 'set_fan');

-- 명령 상태 (pending → sent → acked|failed|timeout)
CREATE TYPE command_status AS ENUM ('pending', 'sent', 'acked', 'failed', 'timeout');

-- 전력 검증 결과
CREATE TYPE verify_result AS ENUM ('success', 'failed', 'uncertain');

-- 실증 운영 방식
CREATE TYPE operation_mode AS ENUM ('baseline', 'rule', 'mpc');

-- 이벤트 분류
CREATE TYPE event_category AS ENUM (
    'sensor_error', 'co2_exceed', 'temp_deviation', 'control_fail',
    'network', 'schedule', 'energy', 'system'
);

-- 이벤트 심각도
CREATE TYPE event_severity AS ENUM ('info', 'warning', 'critical');

-- 이벤트 처리 상태
CREATE TYPE event_status AS ENUM ('open', 'read', 'resolved');

-- 센서 측정 품질 플래그 (v2.3 신규 — 이진값)
CREATE TYPE quality_flag AS ENUM ('ok', 'error');