-- ---------------------------------------------------------------------
-- 004_gateway.sql — 게이트웨이 전용 테이블
--
-- 001~003 은 프론트·API 가 쓰는 핵심 스키마다. 여기에는 게이트웨이(라즈베리
-- 파이의 제어 두뇌)만 쓰는 것을 모은다. 다른 곳에서 참조하지 않으므로 이
-- 파일을 적용하지 않아도 API 와 프론트는 그대로 동작한다.
-- ---------------------------------------------------------------------

-- IR 송수신 방향
DO $$ BEGIN
    CREATE TYPE ir_direction AS ENUM ('tx', 'rx');
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

-- ---------------------------------------------------------------------
-- ir_events — 에어컨 IR 코드 송수신 기록
--
-- 리모컨 코드 학습(rx)과 실제 송신(tx)을 같은 표에 남긴다. 학습된 코드가
-- 맞는지, 송신이 실제로 나갔는지를 나중에 대조하려면 둘이 한곳에 있어야
-- 한다. room_id 는 노드가 아직 공간에 배정되지 않았을 수 있어 NULL 을
-- 허용한다.
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS ir_events (
    ir_event_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    room_id     bigint,
    direction   ir_direction NOT NULL,
    protocol    varchar(30)  NOT NULL DEFAULT 'unknown',
    code_hash   varchar(64)  NOT NULL,
    source      varchar(30)  NOT NULL DEFAULT 'unknown',
    raw_payload jsonb,
    occurred_at timestamptz  NOT NULL,
    CONSTRAINT fk_ir_room FOREIGN KEY (room_id)
        REFERENCES rooms (room_id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_ir_events_room_time
    ON ir_events (room_id, occurred_at DESC);

-- 같은 코드가 몇 번 나갔는지 세는 조회가 잦다.
CREATE INDEX IF NOT EXISTS idx_ir_events_code
    ON ir_events (code_hash, occurred_at DESC);
