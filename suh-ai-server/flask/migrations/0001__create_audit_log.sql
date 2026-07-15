-- Admin action audit log (category/action are code enums, DB uses VARCHAR -- no migration needed on expansion)
CREATE TABLE audit_log (
    id           BIGSERIAL    PRIMARY KEY,
    occurred_at  TIMESTAMPTZ  NOT NULL DEFAULT now(),
    category     VARCHAR(32)  NOT NULL,
    action       VARCHAR(64)  NOT NULL,
    actor_ip     VARCHAR(64)  NOT NULL,
    detail       JSONB        NULL
);

COMMENT ON TABLE audit_log IS 'suh-ai-server admin action audit log';
COMMENT ON COLUMN audit_log.category IS 'service category (code enum: PALWORLD, SYSTEM, ...)';
COMMENT ON COLUMN audit_log.action IS 'action (code enum: SERVER_START, SETTINGS_UPDATE, ...)';
COMMENT ON COLUMN audit_log.detail IS 'action-specific payload (settings diff, etc.)';

CREATE INDEX idx_audit_log_category_occurred_at
    ON audit_log (category, occurred_at DESC);
