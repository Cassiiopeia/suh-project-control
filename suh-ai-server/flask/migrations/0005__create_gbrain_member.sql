-- gbrain team members and their API keys (#221)
-- owner hands keys to members (no member login); token values encrypted with GBRAIN_MEMBER_KEY_SECRET (not in DB)
CREATE TABLE IF NOT EXISTS gbrain_member (
    id SERIAL PRIMARY KEY,
    -- lowercase id, used as gbrain token name prefix
    handle VARCHAR(40) NOT NULL UNIQUE,
    display_name VARCHAR(100) NOT NULL,
    contact VARCHAR(200) NOT NULL DEFAULT '',
    memo VARCHAR(500) NOT NULL DEFAULT '',
    is_owner BOOLEAN NOT NULL DEFAULT FALSE,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    ended_at TIMESTAMPTZ
);

-- encrypted_token: salt(16) | nonce(12) | AES-256-GCM ciphertext+tag, NULL for linked tokens issued before #221
CREATE TABLE IF NOT EXISTS gbrain_member_api_key (
    id SERIAL PRIMARY KEY,
    member_id INTEGER NOT NULL REFERENCES gbrain_member (id),
    -- personal or team project key
    brain_id VARCHAR(64) NOT NULL,
    gbrain_token_id VARCHAR(36) NOT NULL,
    token_name VARCHAR(63) NOT NULL,
    -- comma separated gbrain scopes (read / read,write)
    scopes VARCHAR(100) NOT NULL,
    encrypted_token BYTEA,
    encryption_scheme VARCHAR(40),
    issued_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    revoked_at TIMESTAMPTZ,
    UNIQUE (brain_id, gbrain_token_id)
);

CREATE INDEX IF NOT EXISTS gbrain_member_api_key_member_idx ON gbrain_member_api_key (member_id);

-- owner member: existing personal device tokens are linked here (display_name U&'...' = Korean "owner", file stays ASCII)
INSERT INTO gbrain_member (handle, display_name, memo, is_owner)
VALUES ('owner', U&'\C18C\C720\C790', 'control tower owner devices', TRUE)
ON CONFLICT (handle) DO NOTHING;
