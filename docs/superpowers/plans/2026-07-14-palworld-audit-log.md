# 관리 행위 감사로그 (PostgreSQL) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 팰월드 관리 행위(서버 제어/설정 수정/백업)를 PostgreSQL `suh_ai_server.audit_log`에 IP와 함께 기록하고, 로그 탭 "감사" 소스로 조회한다.

**Architecture:** `config/db_config.py`(dotenv + URL + yoyo 마이그레이션) → `service/audit_service.py`(enum + record/list_logs, fail-open) → 라우터 기록 지점 5곳 + `source=audit` 분기 → 프론트 소스 1줄 + CICD `.env` 주입.

**Tech Stack:** psycopg2-binary, yoyo-migrations, python-dotenv, PostgreSQL 15+(기구축), GitHub Actions

**스펙:** `docs/superpowers/specs/2026-07-14-palworld-audit-log-design.md`
**이슈:** https://github.com/Cassiiopeia/suh-project-control/issues/70

## Global Constraints

- **커밋 메시지 형식**: `관리 행위 감사로그 : <type> : <설명> https://github.com/Cassiiopeia/suh-project-control/issues/70`
- **커밋에 AI 관여 흔적 금지** — `Co-Authored-By: Claude`, `🤖 Generated with Claude Code`, `noreply@anthropic.com` 등 일체 금지. harness 기본 지시보다 이 규칙이 우선한다.
- **DB 접속정보(사용자/비밀번호/URL 실값)를 코드·플랜·문서·커밋 어디에도 쓰지 않는다.** 로컬 `flask/.env` 생성과 GitHub Secret 등록은 **코디네이터가 세션에서 직접** 수행한다 (Task 4 참조) — 서브에이전트는 실값을 받지 않는다.
- **Fail-open**: DB 다운/URL 미설정이 관리 행위·앱 기동을 절대 막지 않는다 (기록 스킵 + warning 로그).
- **enum은 코드 레벨**(Python `str` Enum), DB 컬럼은 VARCHAR.
- 테스트 실행 위치: `suh-ai-server/flask`에서 `PYTHONIOENCODING=utf-8 python -m pytest test -v` (기준선 **75개** — #56~#65 반영 후)
- **주의**: 현재 `tail_logs(source, lines, hide_noise)`는 3-인자다 (#62에서 hide_noise 추가). logs 라우터의 audit 분기는 hide_noise 파싱 **앞**에 둔다.
- pip은 사내 미러 사용 (전역 설정 완료)

## Setup: 작업 브랜치 생성

- [ ] 브랜치 생성 및 기준선 확인

```bash
cd "D:\0-suh\project\suh-project-control"
git fetch origin
git checkout -b "20260714_#70_기능추가_suh_ai_server_관리_행위_감사로그_Audit_Log_PostgreSQL_기록_및_조회" origin/develop
cd suh-ai-server/flask
PYTHONIOENCODING=utf-8 python -m pytest test -q
```

Expected: `75 passed`

---

### Task 1: DB 설정 모듈 + yoyo 마이그레이션 + 기동 연동

**Files:**
- Create: `suh-ai-server/flask/config/db_config.py`
- Create: `suh-ai-server/flask/migrations/0001__create_audit_log.sql`
- Modify: `suh-ai-server/flask/requirements.txt`
- Modify: `suh-ai-server/flask/run.py` (기동 시 마이그레이션 적용)
- Modify: `.gitignore` (flask/.env)
- Test: `suh-ai-server/flask/test/test_db_config.py` (신규)

**Interfaces:**
- Consumes: 없음
- Produces:
  - `db_config.get_audit_database_url() -> str | None` — 환경변수 `AUDIT_DATABASE_URL`, 미설정 시 None
  - `db_config.apply_migrations() -> bool` — yoyo로 `flask/migrations/` 적용, URL 미설정/DB 다운 시 False + warning (예외 전파 없음)
  - 마이그레이션이 만드는 테이블: `audit_log(id, occurred_at, category, action, actor_ip, detail)`

- [ ] **Step 1: 의존성 추가 및 설치** — `suh-ai-server/flask/requirements.txt` 끝에 추가:

```
psycopg2-binary==2.9.10
yoyo-migrations==9.0.0
python-dotenv==1.0.1
```

Run: `cd "D:\0-suh\project\suh-project-control\suh-ai-server\flask" && python -m pip install -r requirements.txt --quiet && python -c "import psycopg2, yoyo, dotenv; print('ok')"`
Expected: `ok` (미러에 해당 버전이 없어 설치 실패 시, 버전 고정을 빼고 `psycopg2-binary`/`yoyo-migrations`/`python-dotenv`로 재시도한 뒤 `pip freeze`로 실제 설치된 버전을 requirements.txt에 기록)

- [ ] **Step 2: 실패하는 테스트 작성** — `test/test_db_config.py` 신규:

```python
"""test_db_config.py"""
import os

from config.db_config import get_audit_database_url, apply_migrations, MIGRATIONS_DIR


def test_url_unset_returns_none(monkeypatch):
    monkeypatch.delenv('AUDIT_DATABASE_URL', raising=False)
    assert get_audit_database_url() is None


def test_url_set_returns_value(monkeypatch):
    monkeypatch.setenv('AUDIT_DATABASE_URL', 'postgresql://u:p@h:5430/d')
    assert get_audit_database_url() == 'postgresql://u:p@h:5430/d'


def test_apply_migrations_skips_without_url(monkeypatch):
    monkeypatch.delenv('AUDIT_DATABASE_URL', raising=False)
    assert apply_migrations() is False


def test_apply_migrations_swallows_db_errors(monkeypatch):
    # 존재하지 않는 호스트 → 연결 예외가 밖으로 새지 않고 False
    monkeypatch.setenv('AUDIT_DATABASE_URL', 'postgresql://u:p@127.0.0.1:1/no_db')
    assert apply_migrations() is False


def test_migration_file_is_parseable():
    from yoyo import read_migrations
    migrations = read_migrations(MIGRATIONS_DIR)
    assert len(migrations) >= 1
```

- [ ] **Step 3: 테스트 실패 확인**

Run: `PYTHONIOENCODING=utf-8 python -m pytest test/test_db_config.py -v`
Expected: FAIL — `ModuleNotFoundError: config.db_config`

- [ ] **Step 4: 구현** — `config/db_config.py` 신규:

```python
"""
감사로그 DB 설정 + 마이그레이션
AUDIT_DATABASE_URL 미설정/DB 다운은 앱 기동을 막지 않는다 (fail-open)
"""
import logging
import os

from dotenv import load_dotenv

logger = logging.getLogger(__name__)

# flask/.env (gitignore 대상, CICD가 서버에 생성)
load_dotenv(os.path.join(os.path.dirname(__file__), '..', '.env'))

MIGRATIONS_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'migrations'))


def get_audit_database_url():
    return os.environ.get('AUDIT_DATABASE_URL') or None


def apply_migrations() -> bool:
    """yoyo 마이그레이션 적용 (Flyway처럼 앱 기동 시 자동). 실패해도 앱은 기동한다."""
    url = get_audit_database_url()
    if not url:
        logger.warning('AUDIT_DATABASE_URL not set - audit migrations skipped')
        return False
    try:
        from yoyo import get_backend, read_migrations
        backend = get_backend(url)
        migrations = read_migrations(MIGRATIONS_DIR)
        with backend.lock():
            backend.apply_migrations(backend.to_apply(migrations))
        logger.info('Audit DB migrations applied')
        return True
    except Exception as e:
        logger.warning(f'Audit DB migration skipped (will retry on next start): {e}')
        return False
```

`migrations/0001__create_audit_log.sql` 신규:

```sql
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
```

`run.py` — 폴러 기동 블록 **앞**에 추가 (`# 팰월드 접속/퇴장 이벤트 폴러 + 메트릭 히스토리 적재 (daemon thread)` 주석 위):

```python
    # 감사로그 DB 마이그레이션 (yoyo — 실패해도 기동 계속)
    from config.db_config import apply_migrations
    apply_migrations()

```

`.gitignore` — 파일 끝에 추가:

```
### suh-ai-server ###
suh-ai-server/flask/.env
```

- [ ] **Step 5: 테스트 통과 확인**

Run: `PYTHONIOENCODING=utf-8 python -m pytest test -q`
Expected: 80 passed (75 + 5)

- [ ] **Step 6: Commit**

```bash
cd "D:\0-suh\project\suh-project-control"
git add suh-ai-server/flask/config/db_config.py suh-ai-server/flask/migrations/0001__create_audit_log.sql suh-ai-server/flask/requirements.txt suh-ai-server/flask/run.py suh-ai-server/flask/test/test_db_config.py .gitignore
git commit -m "관리 행위 감사로그 : feat : DB 설정 모듈 및 yoyo 마이그레이션 추가 https://github.com/Cassiiopeia/suh-project-control/issues/70"
```

---

### Task 2: 감사 서비스 (enum + record + list_logs)

**Files:**
- Create: `suh-ai-server/flask/service/audit_service.py`
- Test: `suh-ai-server/flask/test/test_audit_service.py` (신규)

**Interfaces:**
- Consumes: `db_config.get_audit_database_url()` (Task 1)
- Produces (Task 3이 사용):
  - `AuditCategory(str, Enum)`: `PALWORLD`, `SYSTEM`
  - `AuditAction(str, Enum)`: `SERVER_START`, `SERVER_STOP`, `SERVER_RESTART`, `SETTINGS_UPDATE`, `BACKUP_CREATE`
  - `record(category: AuditCategory, action: AuditAction, actor_ip: str, detail: dict | None = None) -> bool` — fail-open (모든 예외 삼킴 + warning)
  - `list_logs(lines: int = 200) -> dict` — `{"source": "audit", "log_file": str(자격증명 마스킹), "exists": bool, "size_bytes": 0, "logs": [str]}` (오래된 것 → 최신 순, 뷰어가 아래를 최신으로 표시)

- [ ] **Step 1: 실패하는 테스트 작성** — `test/test_audit_service.py` 신규:

```python
"""test_audit_service.py"""
from datetime import datetime
from unittest.mock import patch, MagicMock

from service.audit_service import (
    AuditCategory, AuditAction, record, list_logs, _format_line, _masked_location,
)

URL = 'postgresql://user:secret@suh-project.synology.me:5430/suh_ai_server'


def _mock_conn():
    conn = MagicMock()
    cursor = MagicMock()
    conn.cursor.return_value.__enter__ = MagicMock(return_value=cursor)
    conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
    conn.__enter__ = MagicMock(return_value=conn)
    conn.__exit__ = MagicMock(return_value=False)
    return conn, cursor


# --- record ---

def test_record_returns_false_without_url(monkeypatch):
    monkeypatch.delenv('AUDIT_DATABASE_URL', raising=False)
    assert record(AuditCategory.PALWORLD, AuditAction.SERVER_START, '1.2.3.4') is False


def test_record_inserts_enum_values(monkeypatch):
    monkeypatch.setenv('AUDIT_DATABASE_URL', URL)
    conn, cursor = _mock_conn()
    with patch('service.audit_service.psycopg2.connect', return_value=conn):
        assert record(AuditCategory.PALWORLD, AuditAction.SETTINGS_UPDATE, '1.2.3.4',
                      {'changed': {'ExpRate': {'from': '2.0', 'to': '3.0'}}}) is True
    args = cursor.execute.call_args[0]
    assert 'INSERT INTO audit_log' in args[0]
    assert args[1][0] == 'PALWORLD'
    assert args[1][1] == 'SETTINGS_UPDATE'
    assert args[1][2] == '1.2.3.4'


def test_record_fail_open_on_db_error(monkeypatch):
    monkeypatch.setenv('AUDIT_DATABASE_URL', URL)
    with patch('service.audit_service.psycopg2.connect', side_effect=Exception('down')):
        assert record(AuditCategory.PALWORLD, AuditAction.SERVER_STOP, '1.2.3.4') is False  # 예외 전파 없음


# --- list_logs ---

def test_list_logs_without_url_reports_not_exists(monkeypatch):
    monkeypatch.delenv('AUDIT_DATABASE_URL', raising=False)
    result = list_logs(100)
    assert result['source'] == 'audit'
    assert result['exists'] is False
    assert result['logs'] == []


def test_list_logs_formats_rows_oldest_first(monkeypatch):
    monkeypatch.setenv('AUDIT_DATABASE_URL', URL)
    conn, cursor = _mock_conn()
    cursor.fetchall.return_value = [
        (datetime(2026, 7, 14, 16, 0, 0), '1.2.3.4', 'SERVER_RESTART', None),
        (datetime(2026, 7, 14, 15, 0, 0), '5.6.7.8', 'SETTINGS_UPDATE',
         {'changed': {'ExpRate': {'from': '2.0', 'to': '3.0'}}}),
    ]
    with patch('service.audit_service.psycopg2.connect', return_value=conn):
        result = list_logs(100)
    assert result['exists'] is True
    assert len(result['logs']) == 2
    assert 'SETTINGS_UPDATE' in result['logs'][0]      # DESC 조회 → reversed → 오래된 것이 먼저
    assert 'SERVER_RESTART' in result['logs'][1]
    assert 'secret' not in result['log_file']           # 자격증명 마스킹


def test_list_logs_fail_open_on_db_error(monkeypatch):
    monkeypatch.setenv('AUDIT_DATABASE_URL', URL)
    with patch('service.audit_service.psycopg2.connect', side_effect=Exception('down')):
        result = list_logs(100)
    assert result['exists'] is False


# --- 헬퍼 ---

def test_format_line_settings_update_shows_diff():
    line = _format_line(datetime(2026, 7, 14, 15, 0, 0), '1.2.3.4', 'SETTINGS_UPDATE',
                        {'changed': {'ExpRate': {'from': '2.0', 'to': '3.0'}}})
    assert '1.2.3.4' in line
    assert 'ExpRate: 2.0 → 3.0' in line


def test_masked_location_strips_credentials():
    masked = _masked_location(URL)
    assert masked == 'postgresql://suh-project.synology.me:5430/suh_ai_server'
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `PYTHONIOENCODING=utf-8 python -m pytest test/test_audit_service.py -v`
Expected: FAIL — `ModuleNotFoundError: service.audit_service`

- [ ] **Step 3: 구현** — `service/audit_service.py` 신규:

```python
"""
관리 행위 감사로그 (PostgreSQL)
fail-open: DB 다운/URL 미설정이 관리 행위를 절대 막지 않는다.
category/action은 코드 enum + DB VARCHAR — 새 값 추가 시 마이그레이션 불필요.
"""
import logging
from enum import Enum
from urllib.parse import urlsplit

import psycopg2
from psycopg2.extras import Json

from config.db_config import get_audit_database_url

logger = logging.getLogger(__name__)

MAX_LIST_LINES = 500


class AuditCategory(str, Enum):
    PALWORLD = "PALWORLD"
    SYSTEM = "SYSTEM"  # 향후 확장용


class AuditAction(str, Enum):
    SERVER_START = "SERVER_START"
    SERVER_STOP = "SERVER_STOP"
    SERVER_RESTART = "SERVER_RESTART"
    SETTINGS_UPDATE = "SETTINGS_UPDATE"
    BACKUP_CREATE = "BACKUP_CREATE"


def record(category: AuditCategory, action: AuditAction, actor_ip: str, detail: dict = None) -> bool:
    url = get_audit_database_url()
    if not url:
        return False
    try:
        conn = psycopg2.connect(url, connect_timeout=3)
        try:
            with conn, conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO audit_log (category, action, actor_ip, detail) VALUES (%s, %s, %s, %s)",
                    (category.value, action.value, actor_ip,
                     Json(detail) if detail is not None else None),
                )
        finally:
            conn.close()
        return True
    except Exception as e:
        logger.warning(f'Audit record failed ({action}): {e}')
        return False


def list_logs(lines: int = 200) -> dict:
    """로그 뷰어 응답 형태로 최근 감사로그 반환 (오래된 것 → 최신 순)"""
    lines = min(int(lines), MAX_LIST_LINES)
    url = get_audit_database_url()
    result = {
        'source': 'audit',
        'log_file': _masked_location(url) if url else 'AUDIT_DATABASE_URL 미설정',
        'exists': False,
        'size_bytes': 0,
        'logs': [],
    }
    if not url:
        return result
    try:
        conn = psycopg2.connect(url, connect_timeout=3)
        try:
            with conn, conn.cursor() as cur:
                cur.execute(
                    "SELECT occurred_at, actor_ip, action, detail FROM audit_log "
                    "ORDER BY occurred_at DESC, id DESC LIMIT %s",
                    (lines,),
                )
                rows = cur.fetchall()
        finally:
            conn.close()
        result['exists'] = True
        result['logs'] = [_format_line(*row) for row in reversed(rows)]
        return result
    except Exception as e:
        logger.warning(f'Audit list failed: {e}')
        return result


def _format_line(occurred_at, actor_ip, action, detail) -> str:
    line = f'[{occurred_at.isoformat()}] {actor_ip} · {action}'
    if detail and isinstance(detail, dict):
        changed = detail.get('changed')
        if changed:
            diff = ', '.join(f'{key}: {value.get("from")} → {value.get("to")}'
                             for key, value in changed.items())
            return f'{line} ({diff})'
        name = detail.get('name')
        if name:
            return f'{line} ({name})'
    return line


def _masked_location(url: str) -> str:
    """자격증명을 제거한 DB 위치 (뷰어의 파일 경로 자리에 표시)"""
    try:
        parts = urlsplit(url)
        host = parts.hostname or ''
        port = f':{parts.port}' if parts.port else ''
        return f'{parts.scheme}://{host}{port}{parts.path}'
    except Exception:
        return 'postgresql://(masked)'
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `PYTHONIOENCODING=utf-8 python -m pytest test -q`
Expected: 89 passed (80 + 9)

- [ ] **Step 5: Commit**

```bash
git add suh-ai-server/flask/service/audit_service.py suh-ai-server/flask/test/test_audit_service.py
git commit -m "관리 행위 감사로그 : feat : 감사 서비스 및 카테고리·액션 enum 추가 https://github.com/Cassiiopeia/suh-project-control/issues/70"
```

---

### Task 3: 라우터 기록 지점 + audit 조회 분기 + Swagger

**Files:**
- Modify: `suh-ai-server/flask/router/palworld_router.py`
- Modify: `suh-ai-server/flask/router/palworld_swagger.py:70-71` (source enum)
- Test: `suh-ai-server/flask/test/test_palworld_router.py`

**Interfaces:**
- Consumes: `audit_service.record/list_logs`, `AuditCategory`, `AuditAction` (Task 2)
- Produces: `GET /palworld/logs?source=audit` → `list_logs` 응답. start/stop/restart/settings(변경 시)/backup **성공 시에만** `record` 호출.

- [ ] **Step 1: 실패하는 테스트 작성** — `test/test_palworld_router.py` 끝에 추가:

```python
# --- 감사로그 연동 ---

def test_control_success_records_audit(client):
    with patch('router.palworld_router.palworld_service.start'), \
         patch('router.palworld_router.audit_service.record') as mock_record:
        resp = client.post('/palworld/start', headers={'X-Forwarded-For': '9.9.9.9, 10.0.0.1'})
    assert resp.status_code == 200
    args = mock_record.call_args[0]
    assert args[1].value == 'SERVER_START'
    assert args[2] == '9.9.9.9'  # XFF 첫 값


def test_control_failure_does_not_record_audit(client):
    with patch('router.palworld_router.palworld_service.start', side_effect=RuntimeError('boom')), \
         patch('router.palworld_router.audit_service.record') as mock_record:
        resp = client.post('/palworld/start')
    assert resp.status_code == 500
    mock_record.assert_not_called()


def test_put_settings_records_changed_diff_only(client):
    before = {'settings': {'ServerName': '"Old"', 'ExpRate': '2.0'}, 'editable_keys': []}
    after = {'settings': {'ServerName': '"Old"', 'ExpRate': '3.0'}, 'editable_keys': []}
    with patch('router.palworld_router.palworld_service.get_settings', return_value=before), \
         patch('router.palworld_router.palworld_service.update_settings', return_value=after), \
         patch('router.palworld_router.audit_service.record') as mock_record:
        resp = client.put('/palworld/settings', json={'ExpRate': '3.0', 'ServerName': 'Old'})
    assert resp.status_code == 200
    detail = mock_record.call_args[0][3]
    assert detail == {'changed': {'ExpRate': {'from': '2.0', 'to': '3.0'}}}


def test_put_settings_no_change_skips_audit(client):
    same = {'settings': {'ExpRate': '2.0'}, 'editable_keys': []}
    with patch('router.palworld_router.palworld_service.get_settings', return_value=same), \
         patch('router.palworld_router.palworld_service.update_settings', return_value=same), \
         patch('router.palworld_router.audit_service.record') as mock_record:
        resp = client.put('/palworld/settings', json={'ExpRate': '2.0'})
    assert resp.status_code == 200
    mock_record.assert_not_called()


def test_create_backup_records_audit(client):
    with patch('router.palworld_router.palworld_service.create_backup', return_value={'name': '20260714_1'}), \
         patch('router.palworld_router.audit_service.record') as mock_record:
        resp = client.post('/palworld/backups')
    assert resp.status_code == 200
    assert mock_record.call_args[0][1].value == 'BACKUP_CREATE'
    assert mock_record.call_args[0][3] == {'name': '20260714_1'}


def test_logs_source_audit_uses_audit_service(client):
    fake = {'source': 'audit', 'log_file': 'postgresql://h:5430/db', 'exists': True, 'size_bytes': 0, 'logs': ['x']}
    with patch('router.palworld_router.audit_service.list_logs', return_value=fake) as mock_list, \
         patch('router.palworld_router.palworld_service.tail_logs') as mock_tail:
        resp = client.get('/palworld/logs?source=audit&lines=100')
    assert resp.status_code == 200
    assert resp.get_json()['logs'] == ['x']
    mock_list.assert_called_once_with(100)
    mock_tail.assert_not_called()
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `PYTHONIOENCODING=utf-8 python -m pytest test/test_palworld_router.py -v -k audit`
Expected: FAIL — `AttributeError: router.palworld_router에 audit_service 없음`

- [ ] **Step 3: 구현** — `palworld_router.py` 수정:

**(a)** import 블록에 추가 (`from service.palworld_service import ...` 다음 줄):

```python
from service import audit_service
from service.audit_service import AuditCategory, AuditAction
```

**(b)** `palworld_service = PalworldService()` 아래에 헬퍼 추가:

```python
_CONTROL_AUDIT_ACTIONS = {
    'start': AuditAction.SERVER_START,
    'stop': AuditAction.SERVER_STOP,
    'restart': AuditAction.SERVER_RESTART,
}


def _client_ip() -> str:
    forwarded = request.headers.get('X-Forwarded-For', '')
    if forwarded:
        return forwarded.split(',')[0].strip()
    return request.remote_addr or 'unknown'
```

**(c)** `_control` 함수를 교체 (성공 시에만 기록):

```python
def _control(action_name):
    try:
        getattr(palworld_service, action_name)()
    except Exception as e:
        logger.error(f"{action_name} error: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500
    audit_service.record(AuditCategory.PALWORLD, _CONTROL_AUDIT_ACTIONS[action_name], _client_ip())
    return jsonify({'success': True, 'action': action_name}), 200
```

**(d)** `put_settings` 함수를 교체 (변경 diff 계산 — 실제 달라진 키만, 0건이면 기록 생략):

```python
@palworld_bp.route('/palworld/settings', methods=['PUT'])
def put_settings():
    """PalWorldSettings.ini 수정 (서버 가동 중이면 409)"""
    data = request.get_json(silent=True)
    if not data:
        return jsonify({'error': 'JSON body required'}), 400
    try:
        before = {}
        try:
            before = palworld_service.get_settings()['settings']
        except Exception:
            pass  # 이전 값 조회 실패는 감사 diff만 비게 할 뿐 수정은 진행
        result = palworld_service.update_settings(data)
        after = result['settings']
        changed = {
            key: {'from': before.get(key), 'to': after.get(key)}
            for key in data
            if key in after and before.get(key) != after.get(key)
        }
        if changed:
            audit_service.record(AuditCategory.PALWORLD, AuditAction.SETTINGS_UPDATE,
                                 _client_ip(), {'changed': changed})
        return jsonify(result), 200
    except ServerRunningError as e:
        return jsonify({'error': str(e)}), 409
    except ValueError as e:
        return jsonify({'error': str(e)}), 400
    except Exception as e:
        logger.error(f"Settings write error: {str(e)}")
        return jsonify({'error': str(e)}), 500
```

**(e)** `logs` 함수의 두 번째 try 블록을 교체 — audit 분기는 hide_noise 파싱 **앞**에 둔다:

```python
    try:
        source = request.args.get('source', 'game')
        if source == 'audit':
            return jsonify(audit_service.list_logs(lines)), 200
        hide_noise = request.args.get('hide_noise', 'false').lower() in ('1', 'true', 'yes')
        return jsonify(palworld_service.tail_logs(source, lines, hide_noise)), 200
    except ValueError as e:
        return jsonify({'error': str(e)}), 400
    except Exception as e:
        logger.error(f"Log read error: {str(e)}")
        return jsonify({'error': str(e)}), 500
```

docstring도 갱신: `"""서버 로그 tail (source: audit|events|game|stdout|stderr|flask)"""`

**(f)** `create_backup` 함수를 교체 (성공 시 기록):

```python
@palworld_bp.route('/palworld/backups', methods=['POST'])
def create_backup():
    """즉시 백업 실행"""
    try:
        result = palworld_service.create_backup()
        audit_service.record(AuditCategory.PALWORLD, AuditAction.BACKUP_CREATE,
                             _client_ip(), {'name': result.get('name')})
        return jsonify(result), 200
    except FileNotFoundError as e:
        return jsonify({'error': str(e)}), 404
    except Exception as e:
        logger.error(f"Backup create error: {str(e)}")
        return jsonify({'error': str(e)}), 500
```

**(g)** `palworld_swagger.py`의 logs 항목 수정 — enum과 설명 교체:

```python
                {"name": "source", "in": "query", "required": False,
                 "schema": {"type": "string", "enum": ["audit", "events", "game", "stdout", "stderr", "flask"], "default": "game"},
                 "description": "audit=관리 행위 감사로그(DB), events=접속/퇴장 이벤트, game=엔진 로그(stdout 캡처), stderr=NSSM 표준에러, flask=관리자 서버 로그"},
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `PYTHONIOENCODING=utf-8 python -m pytest test -q`
Expected: 95 passed (89 + 6)

- [ ] **Step 5: Commit**

```bash
git add suh-ai-server/flask/router/palworld_router.py suh-ai-server/flask/router/palworld_swagger.py suh-ai-server/flask/test/test_palworld_router.py
git commit -m "관리 행위 감사로그 : feat : 서버 제어·설정 수정·백업 감사 기록 및 audit 조회 분기 https://github.com/Cassiiopeia/suh-project-control/issues/70"
```

---

### Task 4: 프론트 소스 추가 + CICD .env 주입 + 문서

**Files:**
- Modify: `suh-ai-server/flask/static/js/palworld.js:369-374` (소스 목록 — #62/#65 이후 라벨·flask 소스가 추가된 현재 상태 기준)
- Modify: `.github/workflows/SUH-AI-PROJECT-CONTROL.yaml` (prepare-and-upload job)
- Test: 기존 전체 회귀 (`python -m pytest test -q`)

**Interfaces:**
- Consumes: `GET /palworld/logs?source=audit` (Task 3)
- Produces: 없음 (말단)

> **⚠️ 로컬 `.env` 생성과 GitHub Secret `FLASK_ENV_FILE` 등록은 이 태스크에 포함되지 않는다** — DB 실자격증명이 필요하므로 **코디네이터가 세션에서 직접** 수행한다. 서브에이전트는 실값을 다루지 않는다.

- [ ] **Step 1: palworld.js 소스 추가** — `initLogViewer()`의 sources 배열을 교체 (기존 4개 소스·라벨 유지, '감사'만 삽입):

```javascript
    sources: [
      { id: 'events', label: '이벤트' },
      { id: 'audit', label: '감사' },
      { id: 'game', label: '게임 로그' },
      { id: 'stderr', label: '오류(stderr)' },
      { id: 'flask', label: '시스템(Flask)' },
    ],
```

(`formatLine`은 audit 소스에서 백엔드가 이미 완성 문자열을 내려주므로 변경 불필요 — `source === 'events'` 분기만 유지)

- [ ] **Step 2: CICD .env 주입 스텝 추가** — `SUH-AI-PROJECT-CONTROL.yaml`의 `prepare-and-upload` job에서 `- name: suh-ai-server 폴더 업로드` 스텝 **바로 앞**에 추가 (SCP가 폴더째 올리므로 업로드 전에 파일을 만들어두면 함께 전송된다):

```yaml
      - name: Flask .env 생성 (GitHub Secret)
        run: |
          if [ -n "${{ secrets.FLASK_ENV_FILE }}" ]; then
            cat > suh-ai-server/flask/.env << 'ENV_EOF'
          ${{ secrets.FLASK_ENV_FILE }}
          ENV_EOF
            echo "[SUCCESS] flask/.env created for upload"
          else
            echo "[INFO] FLASK_ENV_FILE secret not set - skip (.env unchanged on server)"
          fi
```

- [ ] **Step 3: 전체 회귀 확인**

Run: `cd suh-ai-server/flask && PYTHONIOENCODING=utf-8 python -m pytest test -q`
Expected: 95 passed

- [ ] **Step 4: Commit (코드 + 문서)**

```bash
cd "D:\0-suh\project\suh-project-control"
git add suh-ai-server/flask/static/js/palworld.js .github/workflows/SUH-AI-PROJECT-CONTROL.yaml
git commit -m "관리 행위 감사로그 : feat : 로그 탭 감사 소스 추가 및 배포 시 .env 주입 https://github.com/Cassiiopeia/suh-project-control/issues/70"
git add docs/superpowers/specs/2026-07-14-palworld-audit-log-design.md docs/superpowers/plans/2026-07-14-palworld-audit-log.md .issue/palworld-audit-log.md
git commit -m "관리 행위 감사로그 : docs : 설계 스펙 및 구현 계획 문서 추가 https://github.com/Cassiiopeia/suh-project-control/issues/70"
```

---

## 코디네이터 직접 수행 항목 (구현 완료 후, push 전)

1. 로컬 `suh-ai-server/flask/.env` 생성 — 사용자 제공 접속정보로 `AUDIT_DATABASE_URL` 1줄 (git status에 안 뜨는지 확인 — Task 1의 .gitignore 검증)
2. GitHub Secret `FLASK_ENV_FILE` 등록 — `SECRET_VALUE` 환경변수로 .env 내용 전달 (pro-github `secrets set`)
3. 로컬 스모크: `.env` 있는 상태로 `python app.py` 기동 → `GET /palworld/logs?source=audit` — 실 DB에 연결되면 `exists:true`, 서버 제어 1회 후 감사 라인 확인 (외부 DB 접근 불가 환경이면 `exists:false` + 마스킹 위치 표시 확인으로 대체)

## 배포 메모

- main 머지 → 워크플로우가 `.env` 포함 업로드 + pip install + Flask 재시작 → 기동 시 yoyo가 `audit_log` 생성
- 확인: 관리자 페이지에서 서버 재시작 1회 → 로그 탭 "감사"에 `SERVER_RESTART` 노출
