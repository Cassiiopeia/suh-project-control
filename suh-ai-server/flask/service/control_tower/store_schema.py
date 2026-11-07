"""관제소 SQLite 스키마: 테이블 8개 + 인덱스 + 기존 DB 열 추가 (시각은 UTC ISO-8601 문자열)"""
from __future__ import annotations

SCHEMA_STATEMENTS = (
    # 점검 원시 결과 (서비스·시각당 1행, 7일 보관)
    """CREATE TABLE IF NOT EXISTS check_result (
        service_id TEXT NOT NULL,
        checked_at TEXT NOT NULL,
        is_external_known INTEGER NOT NULL,
        internal_is_ok INTEGER, internal_is_slow INTEGER, internal_status_code INTEGER,
        internal_latency_milliseconds INTEGER, internal_error TEXT,
        external_is_ok INTEGER, external_is_slow INTEGER, external_status_code INTEGER,
        external_latency_milliseconds INTEGER, external_error TEXT,
        PRIMARY KEY (service_id, checked_at)
    )""",
    "CREATE INDEX IF NOT EXISTS idx_check_result_checked_at ON check_result (checked_at)",
    # 일별 집계 (day = KST 'YYYY-MM-DD', total = 데이터 있는 틱 수, ok = 정상 틱 수, 400일 보관)
    """CREATE TABLE IF NOT EXISTS daily_rollup (
        day TEXT NOT NULL,
        service_id TEXT NOT NULL,
        total INTEGER NOT NULL,
        ok INTEGER NOT NULL,
        PRIMARY KEY (day, service_id)
    )""",
    # 장애 구간 (ended_at NULL = 진행 중, is_within_maintenance: 점검 창 안에서 시작·종료 1, 아니면 0)
    """CREATE TABLE IF NOT EXISTS incident (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        service_id TEXT NOT NULL,
        cause TEXT NOT NULL,
        started_at TEXT NOT NULL,
        ended_at TEXT,
        is_within_maintenance INTEGER NOT NULL DEFAULT 0
    )""",
    # 서비스당 진행 중 장애 1건만 허용
    """CREATE UNIQUE INDEX IF NOT EXISTS idx_incident_one_open_per_service
        ON incident (service_id) WHERE ended_at IS NULL""",
    # 서비스 런타임 상태 (재시작 시 복원)
    """CREATE TABLE IF NOT EXISTS service_state (
        service_id TEXT PRIMARY KEY,
        status TEXT NOT NULL,
        consecutive_failures INTEGER NOT NULL,
        consecutive_successes INTEGER NOT NULL,
        cause TEXT,
        since TEXT,
        last_notified_at TEXT,
        is_down_notified INTEGER NOT NULL
    )""",
    # 이벤트 기록 (dedupe_key 중복 억제, 30일 보관)
    """CREATE TABLE IF NOT EXISTS event_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        project_id TEXT NOT NULL,
        kind TEXT NOT NULL,
        dedupe_key TEXT,
        created_at TEXT NOT NULL
    )""",
    "CREATE INDEX IF NOT EXISTS idx_event_log_dedupe ON event_log (project_id, dedupe_key, created_at)",
    "CREATE INDEX IF NOT EXISTS idx_event_log_created_at ON event_log (created_at)",
    # 디스코드 바인딩 (scope = 프로젝트 id 또는 global, kind = 채널 종류 또는 _category)
    """CREATE TABLE IF NOT EXISTS discord_binding (
        scope TEXT NOT NULL,
        kind TEXT NOT NULL,
        discord_id TEXT NOT NULL,
        PRIMARY KEY (scope, kind)
    )""",
    # 점검 창 (until 이후 만료)
    """CREATE TABLE IF NOT EXISTS maintenance_override (
        service_id TEXT PRIMARY KEY,
        until TEXT NOT NULL,
        reason TEXT NOT NULL
    )""",
    "CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)",
)

# 기존 DB에 없으면 추가하는 열: (테이블, 열 이름, 열 정의)
COLUMN_MIGRATIONS = (
    ("incident", "is_within_maintenance", "INTEGER NOT NULL DEFAULT 0"),
)


def apply_column_migrations(connection) -> None:
    """COLUMN_MIGRATIONS 중 없는 열만 ALTER TABLE ADD COLUMN (반복 실행 안전)"""
    for table_name, column_name, column_definition in COLUMN_MIGRATIONS:
        existing_columns = {row[1] for row in connection.execute(f"PRAGMA table_info({table_name})")}
        if column_name not in existing_columns:
            connection.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_definition}")
