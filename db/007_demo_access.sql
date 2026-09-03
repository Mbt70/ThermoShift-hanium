-- 로그인 입력 없는 심사 시연용 계정을 명시한다.
-- demo token은 API 보안 계층에서 GET만 허용하므로 제어·수정·삭제할 수 없다.
ALTER TABLE users
    ADD COLUMN IF NOT EXISTS is_demo boolean NOT NULL DEFAULT false;

ALTER TABLE users
    ADD COLUMN IF NOT EXISTS demo_owner_user_id bigint;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'fk_users_demo_owner'
    ) THEN
        ALTER TABLE users
            ADD CONSTRAINT fk_users_demo_owner
            FOREIGN KEY (demo_owner_user_id) REFERENCES users(user_id)
            ON DELETE SET NULL;
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS ix_users_active_demo
    ON users (is_demo)
    WHERE is_demo AND deleted_at IS NULL;
