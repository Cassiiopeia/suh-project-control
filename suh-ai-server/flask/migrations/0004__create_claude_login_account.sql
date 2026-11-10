-- Gmail accounts for Claude login code lookup (#184)
-- encrypted_app_password: salt(16) | nonce(12) | AES-256-GCM ciphertext+tag, scheme in encryption_scheme
CREATE TABLE IF NOT EXISTS claude_login_account (
    id SERIAL PRIMARY KEY,
    gmail_address VARCHAR(320) NOT NULL UNIQUE,
    display_name VARCHAR(100) NOT NULL,
    encrypted_app_password BYTEA NOT NULL,
    encryption_scheme VARCHAR(40) NOT NULL,
    is_enabled BOOLEAN NOT NULL DEFAULT TRUE,
    -- last issued code time / last connection test failed
    last_success_at TIMESTAMPTZ,
    is_last_test_failed BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
