"""관제소 SQLite 스키마: 테이블 20개 + 인덱스 + 기존 DB 열 추가 (시각은 UTC ISO-8601 문자열)"""
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
    # 관리자 화면 서비스 덮어쓰기 (NULL 칸 = 원본 값, is_public 1 공개 0 비공개)
    """CREATE TABLE IF NOT EXISTS service_override (
        service_id TEXT PRIMARY KEY,
        name TEXT, status TEXT, is_public INTEGER, sort_order INTEGER, external_url TEXT,
        updated_at TEXT NOT NULL
    )""",
    # 관리자 화면에서 추가한 서비스 (외부 점검만)
    """CREATE TABLE IF NOT EXISTS custom_service (
        id TEXT PRIMARY KEY,
        project_id TEXT NOT NULL,
        name TEXT NOT NULL,
        external_url TEXT NOT NULL,
        status TEXT NOT NULL,
        is_public INTEGER NOT NULL,
        sort_order INTEGER,
        created_at TEXT NOT NULL
    )""",
    # 관리자 화면 프로젝트 덮어쓰기 (is_hidden 1 공개 페이지 숨김 0 표시)
    """CREATE TABLE IF NOT EXISTS project_override (
        project_id TEXT PRIMARY KEY,
        name TEXT, is_hidden INTEGER, sort_order INTEGER,
        updated_at TEXT NOT NULL
    )""",
    # 관리자 화면에서 추가한 프로젝트
    """CREATE TABLE IF NOT EXISTS custom_project (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        sort_order INTEGER,
        created_at TEXT NOT NULL
    )""",
    # 프로젝트별 사용자 정의 알림 종류 (visible_to = 쉼표 구분, 빈 문자열 = 관리자만)
    """CREATE TABLE IF NOT EXISTS project_event_kind (
        project_id TEXT NOT NULL,
        kind TEXT NOT NULL,
        channel_name TEXT NOT NULL,
        visible_to TEXT NOT NULL,
        created_at TEXT NOT NULL,
        PRIMARY KEY (project_id, kind)
    )""",
    # 프로젝트 썸네일 (128px WebP 바이트, content_hash = 상태 페이지 캐시 버전)
    """CREATE TABLE IF NOT EXISTS project_icon (
        project_id TEXT PRIMARY KEY,
        image_webp BLOB NOT NULL,
        content_hash TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )""",
    # 프로젝트별 디스코드 초대 (channel_id = 프로젝트 status 채널, uses_seen = 마지막 귀속 처리 때 사용 횟수)
    """CREATE TABLE IF NOT EXISTS project_invite (
        project_id TEXT PRIMARY KEY,
        invite_code TEXT NOT NULL,
        channel_id TEXT NOT NULL,
        uses_seen INTEGER NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL
    )""",
    # 앱 확인할 일 연동 소스 (mode: pull / push / both, is_enabled 1 사용 0 중지)
    """CREATE TABLE IF NOT EXISTS app_attention_source (
        project_id TEXT NOT NULL,
        source_id TEXT NOT NULL,
        url TEXT NOT NULL,
        is_enabled INTEGER NOT NULL,
        mode TEXT NOT NULL,
        interval_seconds INTEGER NOT NULL,
        timeout_seconds INTEGER NOT NULL,
        stale_after_seconds INTEGER NOT NULL,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        PRIMARY KEY (project_id, source_id)
    )""",
    # 소스별 수집 상태 (last_generated_at = 마지막으로 반영한 스냅샷 시각, next_due_at = 앱이 요청한 다음 수집 시각)
    """CREATE TABLE IF NOT EXISTS app_attention_source_state (
        project_id TEXT NOT NULL,
        source_id TEXT NOT NULL,
        last_attempt_at TEXT, last_success_at TEXT,
        last_result TEXT, last_error TEXT,
        consecutive_failures INTEGER NOT NULL DEFAULT 0,
        etag TEXT, last_generated_at TEXT,
        app TEXT, app_version TEXT, environment TEXT,
        is_baseline_done INTEGER NOT NULL DEFAULT 0,
        failure_alerted_at TEXT,
        next_due_at TEXT,
        PRIMARY KEY (project_id, source_id)
    )""",
    # 확인할 일 항목 현재 값 (missing_since = 스냅샷에서 빠진 시각, raw_json = 앱 원본 항목)
    """CREATE TABLE IF NOT EXISTS app_attention_item (
        project_id TEXT NOT NULL,
        source_id TEXT NOT NULL,
        "key" TEXT NOT NULL,
        kind TEXT NOT NULL, label TEXT NOT NULL, level TEXT NOT NULL,
        "group" TEXT, description TEXT, admin_url TEXT, latest_at TEXT, detail TEXT,
        "count" INTEGER, total INTEGER, "value" REAL, "limit" REAL, unit TEXT, state TEXT,
        raw_json TEXT,
        first_seen_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        missing_since TEXT,
        PRIMARY KEY (project_id, source_id, "key")
    )""",
    # 관리자 항목별 설정 (NULL = 앱 값 / 기본 규칙, is_hidden 1 숨김)
    """CREATE TABLE IF NOT EXISTS app_attention_item_override (
        project_id TEXT NOT NULL,
        source_id TEXT NOT NULL,
        "key" TEXT NOT NULL,
        is_hidden INTEGER, label TEXT, level_policy TEXT, alert_rule TEXT,
        threshold REAL, channel_kind TEXT, mention_role TEXT,
        PRIMARY KEY (project_id, source_id, "key")
    )""",
    # 항목별 알림 기준 상태 (pending_new_count = 쿨다운 중 쌓인 증가분)
    """CREATE TABLE IF NOT EXISTS app_attention_item_alert (
        project_id TEXT NOT NULL,
        source_id TEXT NOT NULL,
        "key" TEXT NOT NULL,
        last_alerted_at TEXT, last_alerted_total INTEGER, last_alerted_count INTEGER, last_alerted_level TEXT,
        is_threshold_exceeded INTEGER NOT NULL DEFAULT 0,
        pending_new_count INTEGER NOT NULL DEFAULT 0,
        last_alerted_state TEXT,
        PRIMARY KEY (project_id, source_id, "key")
    )""",
    # 항목 값 이력 (값이 바뀔 때만 1행, 90일 보관)
    """CREATE TABLE IF NOT EXISTS app_attention_history (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        project_id TEXT NOT NULL,
        source_id TEXT NOT NULL,
        "key" TEXT NOT NULL,
        observed_at TEXT NOT NULL,
        "count" INTEGER, total INTEGER, "value" REAL, state TEXT, level TEXT
    )""",
    "CREATE INDEX IF NOT EXISTS idx_app_attention_history_observed_at ON app_attention_history (observed_at)",
)

# 기존 DB에 없으면 추가하는 열: (테이블, 열 이름, 열 정의)
COLUMN_MIGRATIONS = (
    ("incident", "is_within_maintenance", "INTEGER NOT NULL DEFAULT 0"),
    ("app_attention_item_alert", "last_alerted_state", "TEXT"),
)


def apply_column_migrations(connection) -> None:
    """COLUMN_MIGRATIONS 중 없는 열만 ALTER TABLE ADD COLUMN (반복 실행 안전)"""
    for table_name, column_name, column_definition in COLUMN_MIGRATIONS:
        existing_columns = {row[1] for row in connection.execute(f"PRAGMA table_info({table_name})")}
        if column_name not in existing_columns:
            connection.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_definition}")
