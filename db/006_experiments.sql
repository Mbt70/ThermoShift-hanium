-- ---------------------------------------------------------------------
-- 006 — 가진 실험 기록과 히터 이력.
--
-- 왜 필요한가:
--   목업이 12L 라 사람을 넣을 수 없어서, 재실 열부하를 히팅패드 duty 로
--   만든다(gateway/app/heater.py). 게이트웨이가 그 열원을 직접 지령하므로
--   **재실 인원의 정답을 우리가 안다.** 실측 라벨이 없어 막혀 있던 모델
--   비교 작업이 여기서 풀린다. 그 정답을 남기는 표가 heater_log 다.
--
--   지령한 duty 와 실제로 걸린 duty 는 다를 수 있다. 안전 차단(온도 상한,
--   측정 정지)이 끼어들기 때문이다. 회귀에 넣어야 하는 것은 '실제로 걸린'
--   쪽이므로 둘 다 남긴다.
-- ---------------------------------------------------------------------

CREATE TABLE experiment_runs (
    run_id      bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    room_id     bigint      NOT NULL,
    plan_name   text        NOT NULL,
    -- 계획을 그대로 재현하는 데 필요한 값들(구간 나열 등).
    -- duty 는 (계획, 시작시각, 지금) 만으로 정해지므로, 게이트웨이가
    -- 한밤중에 재시작해도 이 행만 있으면 실험이 이어진다.
    plan        jsonb       NOT NULL,
    started_at  timestamptz NOT NULL,
    ends_at     timestamptz NOT NULL,
    -- 사람이 중간에 멈춘 경우. NULL 이면 계획대로 끝났거나 진행 중이다.
    stopped_at  timestamptz,
    note        text,
    CONSTRAINT fk_run_room FOREIGN KEY (room_id)
        REFERENCES rooms (room_id) ON DELETE RESTRICT,
    CONSTRAINT ck_run_window CHECK (ends_at > started_at)
);

-- 한 공간에서 실험이 둘 이상 동시에 돌면 어느 duty 가 누구 것인지 알 수
-- 없다. 진행 중인 실험은 공간당 하나로 못박는다.
CREATE UNIQUE INDEX uq_run_active ON experiment_runs (room_id)
    WHERE stopped_at IS NULL;

CREATE TABLE heater_log (
    log_id          bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    run_id          bigint,
    requested_duty  smallint     NOT NULL,
    applied_duty    smallint     NOT NULL,
    -- 스케일링 계약으로 환산한 재실 인원 상당. 모델 비교의 정답 라벨이다.
    -- 계약이 바뀌면 뜻이 달라지므로 app/heater.py 를 함께 봐야 한다.
    occupants_equiv numeric(5,2) NOT NULL,
    -- 안전 차단이 걸렸다면 그 사유. 이 구간은 지령과 실제가 다르므로
    -- 분석에서 따로 볼 수 있어야 한다.
    blocked_reason  text,
    recorded_at     timestamptz  NOT NULL,
    CONSTRAINT fk_heater_run FOREIGN KEY (run_id)
        REFERENCES experiment_runs (run_id) ON DELETE SET NULL,
    CONSTRAINT ck_heater_duty CHECK (
        requested_duty BETWEEN 0 AND 100 AND applied_duty BETWEEN 0 AND 100)
);

CREATE INDEX ix_heater_time ON heater_log (recorded_at DESC);
CREATE INDEX ix_heater_run ON heater_log (run_id, recorded_at);
