-- Actor detail columns: actual client IP / proxy chain / UA / success flag
-- actor_ip (raw XFF chain) is kept as the audit source of truth
ALTER TABLE audit_log ADD COLUMN client_ip VARCHAR(64);
ALTER TABLE audit_log ADD COLUMN proxy_chain JSONB;
ALTER TABLE audit_log ADD COLUMN user_agent TEXT;
ALTER TABLE audit_log ADD COLUMN success BOOLEAN NOT NULL DEFAULT true;

-- Backfill: first hop of actor_ip chain -> client_ip, the rest -> proxy_chain
UPDATE audit_log
SET client_ip = btrim(split_part(actor_ip, ',', 1)),
    proxy_chain = CASE
        WHEN position(',' in actor_ip) > 0 THEN
            (SELECT jsonb_agg(btrim(x))
             FROM unnest((string_to_array(actor_ip, ','))[2:]) AS x
             WHERE btrim(x) <> '')
        ELSE NULL
    END
WHERE client_ip IS NULL;

COMMENT ON COLUMN audit_log.client_ip IS 'actual client IP (first XFF hop)';
COMMENT ON COLUMN audit_log.proxy_chain IS 'intermediate proxy IPs (rest of XFF chain)';
COMMENT ON COLUMN audit_log.user_agent IS 'User-Agent header of the request';
COMMENT ON COLUMN audit_log.success IS 'whether the audited action succeeded';
