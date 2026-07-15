-- 관리 행위 감사 로그 (category/action은 코드 enum, DB는 VARCHAR — 확장 시 마이그레이션 불필요)
CREATE TABLE audit_log (
    id           BIGSERIAL    PRIMARY KEY,
    occurred_at  TIMESTAMPTZ  NOT NULL DEFAULT now(),
    category     VARCHAR(32)  NOT NULL,
    action       VARCHAR(64)  NOT NULL,
    actor_ip     VARCHAR(64)  NOT NULL,
    detail       JSONB        NULL
);

COMMENT ON TABLE audit_log IS 'suh-ai-server 관리 행위 감사 로그';
COMMENT ON COLUMN audit_log.category IS '서비스 카테고리 (코드 enum: PALWORLD, SYSTEM, ...)';
COMMENT ON COLUMN audit_log.action IS '행위 (코드 enum: SERVER_START, SETTINGS_UPDATE, ...)';
COMMENT ON COLUMN audit_log.detail IS '액션별 부가정보 (설정 변경 diff 등)';

CREATE INDEX idx_audit_log_category_occurred_at
    ON audit_log (category, occurred_at DESC);
