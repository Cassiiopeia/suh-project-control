-- 관제소 Worker D1 초기 스키마: 상태 키값(meta), 1분 점검 원시(check_run, 7일), 일별 집계(daily_rollup, 90일+)

-- meta 키: last_heartbeat_at, emergency_state(ok|down), emergency_since, config_json, config_version,
--          public_incidents_json, last_rollup_day, today_rollup_json, recent_results_json
CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT
);

-- 크론 1회 = 1행, results_json: {service_id: {is_ok, is_slow, status_code, latency_milliseconds, error}}
CREATE TABLE IF NOT EXISTS check_run (
    id INTEGER PRIMARY KEY,
    checked_at TEXT NOT NULL,
    results_json TEXT NOT NULL
);

-- 7일 지난 원시 삭제용
CREATE INDEX IF NOT EXISTS check_run_checked_at ON check_run (checked_at);

-- day: KST YYYY-MM-DD, total: 점검 횟수, ok: 정상 횟수
CREATE TABLE IF NOT EXISTS daily_rollup (
    day TEXT NOT NULL,
    service_id TEXT NOT NULL,
    total INTEGER NOT NULL,
    ok INTEGER NOT NULL,
    PRIMARY KEY (day, service_id)
);
