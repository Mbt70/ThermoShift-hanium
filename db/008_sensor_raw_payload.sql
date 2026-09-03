-- 원본 MQTT 객체를 측정값과 함께 보존한다.
-- 품질 규칙이나 파서가 바뀌어도 원본에서 재처리할 수 있고,
-- source=synthetic_demo 같은 합성 데이터 표식도 나중에 제외할 수 있다.
ALTER TABLE sensor_env
    ADD COLUMN IF NOT EXISTS raw_payload jsonb NOT NULL DEFAULT '{}'::jsonb;

ALTER TABLE sensor_pir
    ADD COLUMN IF NOT EXISTS raw_payload jsonb NOT NULL DEFAULT '{}'::jsonb;

ALTER TABLE sensor_door
    ADD COLUMN IF NOT EXISTS raw_payload jsonb NOT NULL DEFAULT '{}'::jsonb;
