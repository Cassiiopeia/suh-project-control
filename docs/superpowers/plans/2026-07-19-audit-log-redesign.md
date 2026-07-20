# 감사로그 시스템 전면 개선 구현 계획 (이슈 #104)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 감사로그를 공통 데코레이터 기반 기록 + 구조화 조회 API + 전용 관리자 페이지로 전면 개선한다.

**Architecture:** `util/audit_helper.py`의 `@audited` 데코레이터가 상태 변경 라우트에서 IP/UA/성공여부를 자동 수집해 `audit_service.record()`로 기록한다. `audit_service.query_logs()`가 구조화 조회를 제공하고, 새 `audit_router`(API)와 `/admin/audit` 페이지(테이블 UI)가 이를 소비한다. DB는 마이그레이션 0002로 `client_ip/proxy_chain/user_agent/success` 컬럼을 추가한다.

**Tech Stack:** Flask, psycopg2, yoyo-migrations(기동 시 자동 적용), Vanilla JS + daisyUI(Tailwind 4 빌드), pytest

**Spec:** `docs/superpowers/specs/2026-07-19-audit-log-redesign-design.md`

## Global Constraints

- 모든 응답/주석은 한국어, 주석은 WHY 중심으로 간결하게 (실무 수준)
- 커밋 메시지에 Co-Authored-By 태그 금지
- 커밋 메시지 형식: `감사로그 전면 개선: 전용 페이지, 공통 데코레이터, 기록 보강 : {feat|fix|docs|test} : {설명} https://github.com/Cassiiopeia/suh-project-control/issues/104`
- 감사 기록은 fail-open: DB 다운/URL 미설정이 관리 행위를 절대 막지 않는다
- category/action은 코드 enum + DB VARCHAR — enum 추가 시 마이그레이션 불필요
- `actor_ip` 컬럼은 삭제/변경하지 않는다 (감사 원본 보존, 신규 기록도 계속 채운다)
- 테스트 실행 위치: `suh-ai-server/flask` 디렉토리에서 `python3 -m pytest test/ -q`
- 프론트 CSS는 빌드형(purge): 새 daisyUI 클래스 사용 시 `frontend/`에서 `npm run build` 필요
- 작업 브랜치: `20260719_#104_감사로그_전면_개선` (이미 체크아웃됨)

---

### Task 1: 마이그레이션 0002 + `record()` 확장

**Files:**
- Create: `suh-ai-server/flask/migrations/0002__audit_log_actor_detail.sql`
- Modify: `suh-ai-server/flask/service/audit_service.py`
- Test: `suh-ai-server/flask/test/test_audit_service.py`

**Interfaces:**
- Produces: `record(category, action, actor_ip, detail=None, *, client_ip=None, proxy_chain=None, user_agent=None, success=True) -> bool` — 이후 Task 3 데코레이터가 호출. `client_ip` 미지정 시 `actor_ip`의 첫 콤마 항목으로 자동 유도.

- [ ] **Step 1: 실패하는 테스트 작성** — `test/test_audit_service.py`에 추가:

```python
def test_record_inserts_new_actor_columns(monkeypatch):
    monkeypatch.setenv('AUDIT_DATABASE_URL', URL)
    conn, cursor = _mock_conn()
    with patch('service.audit_service.psycopg2.connect', return_value=conn):
        assert record(AuditCategory.TTS, AuditAction.TTS_START, '1.2.3.4, 10.0.0.1',
                      {'engine': 'supertonic'},
                      client_ip='1.2.3.4', proxy_chain=['10.0.0.1'],
                      user_agent='Mozilla/5.0', success=False) is True
    sql, params = cursor.execute.call_args[0]
    assert 'client_ip' in sql and 'proxy_chain' in sql and 'user_agent' in sql and 'success' in sql
    assert params[4] == '1.2.3.4'          # client_ip
    assert params[6] == 'Mozilla/5.0'      # user_agent
    assert params[7] is False              # success


def test_record_derives_client_ip_from_actor_chain(monkeypatch):
    monkeypatch.setenv('AUDIT_DATABASE_URL', URL)
    conn, cursor = _mock_conn()
    with patch('service.audit_service.psycopg2.connect', return_value=conn):
        assert record(AuditCategory.PALWORLD, AuditAction.SERVER_START,
                      '14.63.73.230, 162.158.186.226, 172.30.1.99') is True
    _, params = cursor.execute.call_args[0]
    assert params[4] == '14.63.73.230'     # 체인 첫 항목이 client_ip로 유도
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `cd suh-ai-server/flask && python3 -m pytest test/test_audit_service.py -q`
Expected: 신규 2건 FAIL (`unexpected keyword argument 'client_ip'`)

- [ ] **Step 3: 마이그레이션 SQL 작성** — `migrations/0002__audit_log_actor_detail.sql` 생성:

```sql
-- 실행 주체 상세화: 실제 클라이언트 IP / 프록시 체인 / UA / 성공여부
-- actor_ip(XFF 원문)는 감사 원본 보존을 위해 유지한다
ALTER TABLE audit_log ADD COLUMN client_ip VARCHAR(64);
ALTER TABLE audit_log ADD COLUMN proxy_chain JSONB;
ALTER TABLE audit_log ADD COLUMN user_agent TEXT;
ALTER TABLE audit_log ADD COLUMN success BOOLEAN NOT NULL DEFAULT true;

-- 백필: actor_ip 콤마 체인의 첫 항목 -> client_ip, 나머지 -> proxy_chain
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
```

- [ ] **Step 4: `record()` 확장** — `service/audit_service.py`의 `record` 함수를 교체:

```python
def record(category: AuditCategory, action: AuditAction, actor_ip: str, detail: dict = None, *,
           client_ip: str = None, proxy_chain: list = None, user_agent: str = None,
           success: bool = True) -> bool:
    url = get_audit_database_url()
    if not url:
        return False
    # client_ip 미지정 호출(백그라운드 등)도 체인 첫 항목으로 실제 IP를 채운다
    if client_ip is None and actor_ip:
        client_ip = actor_ip.split(',')[0].strip()
    try:
        conn = psycopg2.connect(url, connect_timeout=3)
        try:
            with conn, conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO audit_log (category, action, actor_ip, detail, "
                    "client_ip, proxy_chain, user_agent, success) "
                    "VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
                    (category.value, action.value, actor_ip,
                     Json(detail) if detail is not None else None,
                     client_ip,
                     Json(proxy_chain) if proxy_chain else None,
                     user_agent, success),
                )
        finally:
            conn.close()
        return True
    except Exception as e:
        logger.warning(f'Audit record failed ({action}): {e}')
        return False
```

- [ ] **Step 5: 테스트 통과 확인**

Run: `cd suh-ai-server/flask && python3 -m pytest test/test_audit_service.py -q`
Expected: 전체 PASS (기존 테스트 포함 — 새 파라미터는 전부 키워드 옵션이라 하위호환)

- [ ] **Step 6: 커밋**

```bash
git add suh-ai-server/flask/migrations/0002__audit_log_actor_detail.sql suh-ai-server/flask/service/audit_service.py suh-ai-server/flask/test/test_audit_service.py
git commit -m "감사로그 전면 개선: 전용 페이지, 공통 데코레이터, 기록 보강 : feat : 마이그레이션 0002 및 record() 실행 주체 컬럼 확장 https://github.com/Cassiiopeia/suh-project-control/issues/104"
```

---

### Task 2: `query_logs()` 구조화 조회 + `list_logs` 카테고리 표시 보정

**Files:**
- Modify: `suh-ai-server/flask/service/audit_service.py`
- Test: `suh-ai-server/flask/test/test_audit_service.py`

**Interfaces:**
- Produces: `query_logs(category=None, action=None, success=None, search=None, limit=100, before_id=None) -> dict` — 반환: `{'available': bool, 'location': str, 'rows': [dict], 'has_more': bool}`. row: `{id, occurred_at(ISO str), category, action, client_ip, proxy_chain, user_agent, success, detail}`. Task 7의 audit_router가 소비.
- 변경: `_format_line(occurred_at, actor_ip, action, detail, category=None)` — 카테고리 프리픽스와 `engine` detail 표시 추가. `list_logs` 라인 형식: `[ts] ip · PALWORLD/SERVER_START (...)`.

- [ ] **Step 1: 실패하는 테스트 작성** — `test/test_audit_service.py`에 추가:

```python
from service.audit_service import query_logs


def test_query_logs_without_url_reports_unavailable(monkeypatch):
    monkeypatch.delenv('AUDIT_DATABASE_URL', raising=False)
    result = query_logs()
    assert result['available'] is False
    assert result['rows'] == []


def test_query_logs_builds_filters_and_rows(monkeypatch):
    monkeypatch.setenv('AUDIT_DATABASE_URL', URL)
    conn, cursor = _mock_conn()
    cursor.fetchall.return_value = [
        (2, datetime(2026, 7, 19, 6, 10, 53), 'TTS', 'TTS_START',
         '14.63.73.230, 162.158.186.226', '14.63.73.230', ['162.158.186.226'],
         'Mozilla/5.0', True, {'engine': 'supertonic'}),
    ]
    with patch('service.audit_service.psycopg2.connect', return_value=conn):
        result = query_logs(category='TTS', action='TTS_START', success=True,
                            search='supertonic', limit=50, before_id=100)
    sql, params = cursor.execute.call_args[0]
    assert 'category = %s' in sql and 'action = %s' in sql and 'success = %s' in sql
    assert 'id < %s' in sql and 'ILIKE' in sql
    assert result['available'] is True
    row = result['rows'][0]
    assert row['id'] == 2
    assert row['category'] == 'TTS'
    assert row['client_ip'] == '14.63.73.230'
    assert row['detail'] == {'engine': 'supertonic'}
    assert row['occurred_at'] == '2026-07-19T06:10:53'


def test_query_logs_has_more_pagination(monkeypatch):
    monkeypatch.setenv('AUDIT_DATABASE_URL', URL)
    conn, cursor = _mock_conn()
    # limit+1 조회로 다음 페이지 존재를 판정한다
    cursor.fetchall.return_value = [
        (i, datetime(2026, 7, 19, 6, 0, 0), 'PALWORLD', 'SERVER_START',
         '1.2.3.4', '1.2.3.4', None, None, True, None) for i in range(3, 0, -1)
    ]
    with patch('service.audit_service.psycopg2.connect', return_value=conn):
        result = query_logs(limit=2)
    assert result['has_more'] is True
    assert len(result['rows']) == 2


def test_query_logs_backfills_client_ip_from_actor(monkeypatch):
    monkeypatch.setenv('AUDIT_DATABASE_URL', URL)
    conn, cursor = _mock_conn()
    # 마이그레이션 전 기록(client_ip NULL)도 조회 시 체인 첫 항목으로 보정
    cursor.fetchall.return_value = [
        (1, datetime(2026, 7, 15, 6, 18, 28), 'PALWORLD', 'SERVER_RESTART',
         '59.15.154.120, 10.0.0.1', None, None, None, True, None),
    ]
    with patch('service.audit_service.psycopg2.connect', return_value=conn):
        result = query_logs()
    assert result['rows'][0]['client_ip'] == '59.15.154.120'


def test_format_line_includes_category_and_engine():
    line = _format_line(datetime(2026, 7, 19, 6, 17, 9), '14.63.73.230', 'TTS_START',
                        {'engine': 'supertonic'}, category='TTS')
    assert 'TTS/TTS_START' in line
    assert 'supertonic' in line
```

기존 테스트 2건 수정 (`_format_line` 시그니처/라인 형식 변경 반영):

```python
def test_list_logs_formats_rows_oldest_first(monkeypatch):
    monkeypatch.setenv('AUDIT_DATABASE_URL', URL)
    conn, cursor = _mock_conn()
    cursor.fetchall.return_value = [
        (datetime(2026, 7, 14, 16, 0, 0), '1.2.3.4', 'SERVER_RESTART', None, 'PALWORLD'),
        (datetime(2026, 7, 14, 15, 0, 0), '5.6.7.8', 'SETTINGS_UPDATE',
         {'changed': {'ExpRate': {'from': '2.0', 'to': '3.0'}}}, 'PALWORLD'),
    ]
    with patch('service.audit_service.psycopg2.connect', return_value=conn):
        result = list_logs(100)
    assert result['exists'] is True
    assert len(result['logs']) == 2
    assert 'SETTINGS_UPDATE' in result['logs'][0]      # DESC 조회 → reversed → 오래된 것이 먼저
    assert 'PALWORLD/' in result['logs'][0]            # 카테고리 프리픽스
    assert 'SERVER_RESTART' in result['logs'][1]
    assert 'secret' not in result['log_file']           # 자격증명 마스킹


def test_format_line_settings_update_shows_diff():
    line = _format_line(datetime(2026, 7, 14, 15, 0, 0), '1.2.3.4', 'SETTINGS_UPDATE',
                        {'changed': {'ExpRate': {'from': '2.0', 'to': '3.0'}}}, category='PALWORLD')
    assert '1.2.3.4' in line
    assert 'ExpRate: 2.0 → 3.0' in line
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `cd suh-ai-server/flask && python3 -m pytest test/test_audit_service.py -q`
Expected: 신규/수정 테스트 FAIL (`cannot import name 'query_logs'` 등)

- [ ] **Step 3: 구현** — `service/audit_service.py`에 `query_logs` 추가, `list_logs`/`_format_line` 수정:

```python
def query_logs(category: str = None, action: str = None, success: bool = None,
               search: str = None, limit: int = 100, before_id: int = None) -> dict:
    """전용 감사로그 페이지용 구조화 조회 (최신순, 키셋 페이징)"""
    limit = min(max(int(limit), 1), MAX_LIST_LINES)
    url = get_audit_database_url()
    result = {
        'available': False,
        'location': _masked_location(url) if url else 'AUDIT_DATABASE_URL 미설정',
        'rows': [],
        'has_more': False,
    }
    if not url:
        return result
    where, params = [], []
    if category:
        where.append('category = %s'); params.append(category)
    if action:
        where.append('action = %s'); params.append(action)
    if success is not None:
        where.append('success = %s'); params.append(success)
    if before_id is not None:
        where.append('id < %s'); params.append(before_id)
    if search:
        like = f'%{search}%'
        where.append('(client_ip ILIKE %s OR actor_ip ILIKE %s OR action ILIKE %s '
                     'OR detail::text ILIKE %s)')
        params.extend([like, like, like, like])
    sql = ('SELECT id, occurred_at, category, action, actor_ip, client_ip, '
           'proxy_chain, user_agent, success, detail FROM audit_log')
    if where:
        sql += ' WHERE ' + ' AND '.join(where)
    sql += ' ORDER BY id DESC LIMIT %s'
    params.append(limit + 1)  # 한 건 더 조회해 다음 페이지 유무 판정
    try:
        conn = psycopg2.connect(url, connect_timeout=3)
        try:
            with conn, conn.cursor() as cur:
                cur.execute(sql, tuple(params))
                rows = cur.fetchall()
        finally:
            conn.close()
        result['available'] = True
        result['has_more'] = len(rows) > limit
        for (row_id, occurred_at, cat, act, actor_ip, client_ip,
             proxy_chain, user_agent, ok, detail) in rows[:limit]:
            # 마이그레이션 전 기록은 client_ip가 비어 있으므로 체인 첫 항목으로 보정
            if not client_ip and actor_ip:
                client_ip = actor_ip.split(',')[0].strip()
            result['rows'].append({
                'id': row_id,
                'occurred_at': occurred_at.isoformat(),
                'category': cat,
                'action': act,
                'client_ip': client_ip,
                'proxy_chain': proxy_chain,
                'user_agent': user_agent,
                'success': ok,
                'detail': detail,
            })
        return result
    except Exception as e:
        logger.warning(f'Audit query failed: {e}')
        return result
```

`list_logs`의 SELECT/포맷 호출 수정 (category 포함):

```python
                cur.execute(
                    "SELECT occurred_at, actor_ip, action, detail, category FROM audit_log "
                    "ORDER BY occurred_at DESC, id DESC LIMIT %s",
                    (lines,),
                )
```

```python
        result['logs'] = [_format_line(*row) for row in reversed(rows)]
```

`_format_line` 교체 (category 프리픽스 + engine 표시):

```python
def _format_line(occurred_at, actor_ip, action, detail, category=None) -> str:
    action_label = f'{category}/{action}' if category else action
    line = f'[{occurred_at.isoformat()}] {actor_ip} · {action_label}'
    if detail and isinstance(detail, dict):
        changed = detail.get('changed')
        if changed and isinstance(changed, dict):
            parts = []
            for key, value in changed.items():
                if isinstance(value, dict):
                    parts.append(f'{key}: {value.get("from")} → {value.get("to")}')
                else:
                    parts.append(f'{key}: {value}')
            return f'{line} ({", ".join(parts)})'
        # 대표 식별자 하나를 괄호로 노출 (보이스명, 엔진명, 모델명 순)
        name = detail.get('name') or detail.get('engine') or detail.get('voice_id')
        if name:
            return f'{line} ({name})'
    return line
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `cd suh-ai-server/flask && python3 -m pytest test/test_audit_service.py -q`
Expected: 전체 PASS

- [ ] **Step 5: 커밋**

```bash
git add suh-ai-server/flask/service/audit_service.py suh-ai-server/flask/test/test_audit_service.py
git commit -m "감사로그 전면 개선: 전용 페이지, 공통 데코레이터, 기록 보강 : feat : query_logs 구조화 조회 및 라인 포맷 카테고리 표시 https://github.com/Cassiiopeia/suh-project-control/issues/104"
```

---

### Task 3: `@audited` 공통 데코레이터 (`util/audit_helper.py`)

**Files:**
- Create: `suh-ai-server/flask/util/audit_helper.py`
- Test: `suh-ai-server/flask/test/test_audit_helper.py`

**Interfaces:**
- Produces (Task 4~6 라우터가 사용):
  - `audited(category: AuditCategory, action: AuditAction = None)` — 라우트 데코레이터. `action=None`이면 핸들러가 `set_audit_action()`으로 지정해야 하며, 미지정 시 기록을 건너뛴다(검증 실패 404 등 감사 대상 아님).
  - `set_audit_action(action: AuditAction)` — 동적 액션 지정
  - `set_audit_detail(detail: dict)` — detail 병합(여러 번 호출 가능)
  - `skip_audit()` — 이번 요청 기록 생략 (예: 설정 변경 diff가 빈 경우)
  - `client_info() -> dict` — `{'actor_ip', 'client_ip', 'proxy_chain', 'user_agent'}` (XFF 첫 항목=client, 나머지=proxy)

- [ ] **Step 1: 실패하는 테스트 작성** — `test/test_audit_helper.py` 생성:

```python
"""test_audit_helper.py — @audited 데코레이터 규약 검증"""
from unittest.mock import patch

import pytest
from flask import Flask, jsonify

from service.audit_service import AuditCategory, AuditAction
from util.audit_helper import audited, set_audit_action, set_audit_detail, skip_audit, client_info


@pytest.fixture
def app():
    app = Flask(__name__)

    @app.route('/ok', methods=['POST'])
    @audited(AuditCategory.PALWORLD, AuditAction.SERVER_START)
    def ok():
        return jsonify({'success': True}), 200

    @app.route('/fail', methods=['POST'])
    @audited(AuditCategory.PALWORLD, AuditAction.SERVER_STOP)
    def fail():
        return jsonify({'error': 'boom'}), 500

    @app.route('/boom', methods=['POST'])
    @audited(AuditCategory.PALWORLD, AuditAction.SERVER_RESTART)
    def boom():
        raise RuntimeError('unexpected')

    @app.route('/dynamic', methods=['POST'])
    @audited(AuditCategory.TTS)
    def dynamic():
        set_audit_action(AuditAction.TTS_START)
        set_audit_detail({'engine': 'supertonic'})
        return jsonify({'success': True}), 200

    @app.route('/unresolved', methods=['POST'])
    @audited(AuditCategory.TTS)
    def unresolved():
        return jsonify({'error': 'unknown'}), 404  # action 미지정 → 기록 안 함

    @app.route('/skip', methods=['POST'])
    @audited(AuditCategory.PALWORLD, AuditAction.SETTINGS_UPDATE)
    def skip():
        skip_audit()
        return jsonify({'success': True}), 200

    @app.route('/info', methods=['POST'])
    def info():
        return jsonify(client_info()), 200

    return app


@pytest.fixture
def client(app):
    return app.test_client()


XFF = {'X-Forwarded-For': '14.63.73.230, 162.158.186.226, 172.30.1.99',
       'User-Agent': 'TestAgent/1.0'}


def test_success_records_with_client_info(client):
    with patch('util.audit_helper.audit_service.record') as mock_record:
        resp = client.post('/ok', headers=XFF)
    assert resp.status_code == 200
    args, kwargs = mock_record.call_args
    assert args[0] == AuditCategory.PALWORLD
    assert args[1] == AuditAction.SERVER_START
    assert args[2] == '14.63.73.230, 162.158.186.226, 172.30.1.99'  # actor_ip 원문 유지
    assert kwargs['client_ip'] == '14.63.73.230'
    assert kwargs['proxy_chain'] == ['162.158.186.226', '172.30.1.99']
    assert kwargs['user_agent'] == 'TestAgent/1.0'
    assert kwargs['success'] is True


def test_error_status_records_failure(client):
    with patch('util.audit_helper.audit_service.record') as mock_record:
        resp = client.post('/fail', headers=XFF)
    assert resp.status_code == 500
    assert mock_record.call_args.kwargs['success'] is False


def test_exception_records_failure_and_reraises(app, client):
    app.config['PROPAGATE_EXCEPTIONS'] = False  # Flask 기본 500 처리 경로
    with patch('util.audit_helper.audit_service.record') as mock_record:
        resp = client.post('/boom', headers=XFF)
    assert resp.status_code == 500
    kwargs = mock_record.call_args.kwargs
    assert kwargs['success'] is False
    assert 'unexpected' in (mock_record.call_args.args[3] or {}).get('error', '')


def test_dynamic_action_and_detail(client):
    with patch('util.audit_helper.audit_service.record') as mock_record:
        client.post('/dynamic', headers=XFF)
    args = mock_record.call_args.args
    assert args[1] == AuditAction.TTS_START
    assert args[3] == {'engine': 'supertonic'}


def test_unresolved_action_skips_record(client):
    with patch('util.audit_helper.audit_service.record') as mock_record:
        client.post('/unresolved', headers=XFF)
    mock_record.assert_not_called()


def test_skip_audit_suppresses_record(client):
    with patch('util.audit_helper.audit_service.record') as mock_record:
        client.post('/skip', headers=XFF)
    mock_record.assert_not_called()


def test_client_info_without_xff_uses_remote_addr(client):
    resp = client.post('/info')
    data = resp.get_json()
    assert data['client_ip'] == '127.0.0.1'   # 테스트 클라이언트 기본 remote_addr
    assert data['proxy_chain'] == []
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `cd suh-ai-server/flask && python3 -m pytest test/test_audit_helper.py -q`
Expected: FAIL (`No module named 'util.audit_helper'`)

- [ ] **Step 3: 구현** — `util/audit_helper.py` 생성:

```python
"""
관리 행위 감사 공통 데코레이터

규칙 (에이전트/개발자 공통 — flask/CLAUDE.md 참고):
- 상태를 변경하는 관리 엔드포인트(POST/PUT/DELETE)에는 반드시 @audited를 부착한다.
- 응답 status < 400 이면 success=True, 그 외/예외는 success=False로 자동 기록된다.
- 동적 값은 핸들러 안에서 set_audit_action()/set_audit_detail()로 지정한다.
- 감사 대상이 아닌 요청(검증 실패 등)은 action 미지정 또는 skip_audit()로 생략된다.
- 요청 컨텍스트 밖(백그라운드 스레드)은 audit_service.record()를 직접 호출한다.
"""
import logging
from functools import wraps

from flask import g, request

from service import audit_service
from service.audit_service import AuditAction, AuditCategory

logger = logging.getLogger(__name__)


def client_info() -> dict:
    """XFF 체인 분해: 첫 항목=실제 클라이언트, 나머지=경유 프록시"""
    forwarded = request.headers.get('X-Forwarded-For', '')
    hops = [h.strip() for h in forwarded.split(',') if h.strip()]
    fallback = request.remote_addr or 'unknown'
    return {
        'actor_ip': forwarded if hops else fallback,  # 하위호환용 원문 체인
        'client_ip': hops[0] if hops else fallback,
        'proxy_chain': hops[1:],
        'user_agent': request.headers.get('User-Agent'),
    }


def set_audit_action(action: AuditAction):
    g.audit_action = action


def set_audit_detail(detail: dict):
    merged = getattr(g, 'audit_detail', None) or {}
    merged.update(detail)
    g.audit_detail = merged


def skip_audit():
    g.audit_skip = True


def audited(category: AuditCategory, action: AuditAction = None):
    """상태 변경 라우트용 감사 데코레이터. action=None이면 set_audit_action() 필수."""
    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            try:
                resp = fn(*args, **kwargs)
            except Exception as e:
                _record(category, action, success=False, error=str(e))
                raise  # 감사 기록 후 기존 에러 흐름 유지
            status = _status_of(resp)
            _record(category, action, success=status < 400)
            return resp
        return wrapper
    return decorator


def _status_of(resp) -> int:
    """Flask 뷰 반환값(Response 또는 (body, status) 튜플)에서 status 추출"""
    if isinstance(resp, tuple) and len(resp) >= 2 and isinstance(resp[1], int):
        return resp[1]
    return getattr(resp, 'status_code', 200)


def _record(category, default_action, success, error=None):
    try:
        if getattr(g, 'audit_skip', False):
            return
        resolved = getattr(g, 'audit_action', None) or default_action
        if resolved is None:
            return  # 검증 실패 등 감사 대상 아님
        detail = getattr(g, 'audit_detail', None)
        if error:
            detail = {**(detail or {}), 'error': error}
        info = client_info()
        audit_service.record(
            category, resolved, info['actor_ip'], detail,
            client_ip=info['client_ip'], proxy_chain=info['proxy_chain'],
            user_agent=info['user_agent'], success=success,
        )
    except Exception as e:
        # 감사 실패가 원 요청을 깨지 않게 격리 (fail-open)
        logger.warning(f'Audit decorator record failed: {e}')
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `cd suh-ai-server/flask && python3 -m pytest test/test_audit_helper.py -q`
Expected: 전체 PASS

- [ ] **Step 5: 커밋**

```bash
git add suh-ai-server/flask/util/audit_helper.py suh-ai-server/flask/test/test_audit_helper.py
git commit -m "감사로그 전면 개선: 전용 페이지, 공통 데코레이터, 기록 보강 : feat : @audited 공통 감사 데코레이터 도입 https://github.com/Cassiiopeia/suh-project-control/issues/104"
```

---

### Task 4: palworld_router 데코레이터 이관

**Files:**
- Modify: `suh-ai-server/flask/router/palworld_router.py`
- Test: `suh-ai-server/flask/test/test_palworld_router.py`

**Interfaces:**
- Consumes: Task 3의 `audited`, `set_audit_detail`, `skip_audit`, `client_info`
- 동작 변화: 제어 실패도 success=False로 기록된다 (기존: 미기록). 설정 변경 diff 없으면 기존대로 기록 생략.

- [ ] **Step 1: 라우터 수정** — `router/palworld_router.py`:

임포트/헬퍼 교체 (기존 `_client_ip` 함수 삭제):

```python
from service import audit_service
from service import palworld_updater
from service.audit_service import AuditCategory, AuditAction
from util.audit_helper import audited, client_info, set_audit_detail, skip_audit
```

`_control`에서 감사 코드 제거, 각 라우트에 데코레이터 부착:

```python
def _control(action_name):
    try:
        getattr(palworld_service, action_name)()
    except Exception as e:
        logger.error(f"{action_name} error: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500
    return jsonify({'success': True, 'action': action_name}), 200


@palworld_bp.route('/palworld/start', methods=['POST'])
@audited(AuditCategory.PALWORLD, AuditAction.SERVER_START)
def start():
    """서버 시작"""
    return _control('start')


@palworld_bp.route('/palworld/stop', methods=['POST'])
@audited(AuditCategory.PALWORLD, AuditAction.SERVER_STOP)
def stop():
    """서버 중지"""
    return _control('stop')


@palworld_bp.route('/palworld/restart', methods=['POST'])
@audited(AuditCategory.PALWORLD, AuditAction.SERVER_RESTART)
def restart():
    """서버 재시작"""
    return _control('restart')
```

`put_settings`: 데코레이터 부착, 기존 `audit_service.record(...)` 블록을 `set_audit_detail`/`skip_audit`로 교체:

```python
@palworld_bp.route('/palworld/settings', methods=['PUT'])
@audited(AuditCategory.PALWORLD, AuditAction.SETTINGS_UPDATE)
def put_settings():
    ...(기존 diff 계산 로직 그대로)...
        if changed:
            set_audit_detail({'changed': changed, 'applied': applied})
        else:
            skip_audit()  # 실변경 없는 저장은 감사 잡음이라 기록하지 않는다
        return jsonify(result), 200
```

`create_backup`: 데코레이터 부착, record 호출을 `set_audit_detail`로 교체:

```python
@palworld_bp.route('/palworld/backups', methods=['POST'])
@audited(AuditCategory.PALWORLD, AuditAction.BACKUP_CREATE)
def create_backup():
    """즉시 백업 실행"""
    try:
        result = palworld_service.create_backup()
        set_audit_detail({'name': result.get('name')})
        return jsonify(result), 200
    except FileNotFoundError as e:
        return jsonify({'error': str(e)}), 404
    except Exception as e:
        logger.error(f"Backup create error: {str(e)}")
        return jsonify({'error': str(e)}), 500
```

`update_server`의 `_client_ip()` 호출은 `client_info()['client_ip']`로 교체 (updater가 자체 record하므로 데코레이터는 달지 않는다 — 이중 기록 방지):

```python
    if not palworld_updater.start_update('manual', client_info()['client_ip']):
```

- [ ] **Step 2: 테스트 수정** — `test/test_palworld_router.py`에서 patch 대상을 데코레이터 경유로 변경. `router.palworld_router.audit_service.record` patch를 전부 `util.audit_helper.audit_service.record`로 바꾼다. 동작 변화 반영 2건:

```python
def test_control_failure_records_failed_audit(client):
    """실패한 제어 시도도 success=False로 감사에 남는다 (기존: 미기록 → 변경)"""
    with patch.object(palworld_router.palworld_service, 'start', side_effect=Exception('svc down')), \
         patch('util.audit_helper.audit_service.record') as mock_record:
        resp = client.post('/palworld/start')
    assert resp.status_code == 500
    assert mock_record.call_args.kwargs['success'] is False


def test_control_success_records_audit(client):
    with patch.object(palworld_router.palworld_service, 'start', return_value=None), \
         patch('util.audit_helper.audit_service.record') as mock_record:
        resp = client.post('/palworld/start')
    assert resp.status_code == 200
    args = mock_record.call_args.args
    assert args[0] == AuditCategory.PALWORLD
    assert args[1] == AuditAction.SERVER_START
```

주의: 기존 테스트 중 `test_control_unmapped_action_skips_audit`는 `_control`이 더 이상 감사를 몰라 의미가 없어졌으므로 삭제한다. 나머지 record 관련 테스트는 patch 경로만 교체하고 assert의 위치 인자 구조(`call_args[0]`)가 데코레이터 호출 형식과 맞는지 확인해 보정한다.

- [ ] **Step 3: 테스트 실행/보정**

Run: `cd suh-ai-server/flask && python3 -m pytest test/test_palworld_router.py -q`
Expected: 전체 PASS (실패 시 patch 경로/assert 형식 보정)

- [ ] **Step 4: 커밋**

```bash
git add suh-ai-server/flask/router/palworld_router.py suh-ai-server/flask/test/test_palworld_router.py
git commit -m "감사로그 전면 개선: 전용 페이지, 공통 데코레이터, 기록 보강 : feat : 팰월드 라우터 @audited 이관 및 실패 시도 기록 https://github.com/Cassiiopeia/suh-project-control/issues/104"
```

---

### Task 5: tts_router 데코레이터 이관

**Files:**
- Modify: `suh-ai-server/flask/router/tts_router.py`
- Test: `suh-ai-server/flask/test/test_tts_router.py`

**Interfaces:**
- Consumes: Task 3의 `audited`, `set_audit_action`, `set_audit_detail`

- [ ] **Step 1: 라우터 수정** — `router/tts_router.py`:

임포트 교체 (기존 `_client_ip` 함수 삭제):

```python
from util.audit_helper import audited, set_audit_action, set_audit_detail
```

`engine_control` — 동적 action이므로 데코레이터에는 category만, 검증 통과 직후 action/detail 지정 (검증 실패 404는 action 미지정이라 기록 안 됨):

```python
@tts_bp.route('/tts/engines/<engine_id>/<action>', methods=['POST'])
@audited(AuditCategory.TTS)
def engine_control(engine_id, action):
    """엔진 설치/시작/중지 — 관리 행위라 감사로그 기록"""
    if engine_id not in TTS_ENGINES:
        return jsonify({'error': f'알 수 없는 엔진: {engine_id}'}), 404
    if action not in _CONTROL_AUDIT_ACTIONS:
        return jsonify({'error': f'알 수 없는 동작: {action}'}), 404
    set_audit_action(_CONTROL_AUDIT_ACTIONS[action])
    set_audit_detail({'engine': engine_id})
    try:
        getattr(tts_service, action)(engine_id)
    except ValueError as e:  # 미설치 상태 start, 중복 install 등
        return jsonify({'error': str(e)}), 409
    except Exception as e:
        logger.error(f"TTS engine {action} failed ({engine_id}): {str(e)}")
        return jsonify({'error': str(e)}), 500
    return jsonify({'success': True, 'engines': tts_service.get_engines_state()}), 200
```

`add_voice` — 데코레이터 부착, record 호출을 `set_audit_detail`로 교체:

```python
@tts_bp.route('/tts/voices', methods=['POST'])
@audited(AuditCategory.TTS, AuditAction.TTS_VOICE_ADD)
def add_voice():
    """보이스 클로닝용 레퍼런스 음성 등록 (multipart: name + file)"""
    name = (request.form.get('name') or '').strip()
    file = request.files.get('file')
    if not file:
        return jsonify({'error': 'file(WAV)이 필요합니다'}), 400
    try:
        entry = voice_store.add(name, file.read())
    except ValueError as e:
        return jsonify({'error': str(e)}), 400
    set_audit_detail({'voice_id': entry['id'], 'name': entry['name']})
    logger.info(f"TTS voice added: {entry['id']} ({entry['name']})")
    return jsonify({'success': True, 'voice': entry}), 200
```

`delete_voice` — 데코레이터 부착, 시도 자체가 남도록 detail을 검증 직후 지정:

```python
@tts_bp.route('/tts/voices/<voice_id>', methods=['DELETE'])
@audited(AuditCategory.TTS, AuditAction.TTS_VOICE_DELETE)
def delete_voice(voice_id):
    """사용자 등록 보이스 삭제 — 내장 보이스는 삭제 불가"""
    set_audit_detail({'voice_id': voice_id})
    if voice_id in _builtin_voice_ids():
        return jsonify({'error': '내장 보이스는 삭제할 수 없습니다'}), 403
    try:
        voice_store.delete(voice_id)
    except KeyError:
        return jsonify({'error': f'보이스를 찾을 수 없습니다: {voice_id}'}), 404
    return jsonify({'success': True, 'voice_id': voice_id}), 200
```

- [ ] **Step 2: 테스트 수정** — `test/test_tts_router.py`의 `monkeypatch.setattr(tts_router_module.audit_service, 'record', ...)` 패턴을 `util.audit_helper`의 audit_service로 교체:

```python
import util.audit_helper as audit_helper_module
    monkeypatch.setattr(audit_helper_module.audit_service, 'record', ...)
```

호출 형식 검증부는 데코레이터 규약(위치 인자: category, action, actor_ip, detail / 키워드: client_ip 등)에 맞게 보정한다.

- [ ] **Step 3: 테스트 실행/보정**

Run: `cd suh-ai-server/flask && python3 -m pytest test/test_tts_router.py -q`
Expected: 전체 PASS

- [ ] **Step 4: 커밋**

```bash
git add suh-ai-server/flask/router/tts_router.py suh-ai-server/flask/test/test_tts_router.py
git commit -m "감사로그 전면 개선: 전용 페이지, 공통 데코레이터, 기록 보강 : feat : TTS 라우터 @audited 이관 https://github.com/Cassiiopeia/suh-project-control/issues/104"
```

---

### Task 6: 모델 관리 감사 추가 (MODEL 카테고리)

**Files:**
- Modify: `suh-ai-server/flask/service/audit_service.py` (enum 추가)
- Modify: `suh-ai-server/flask/router/model_router.py`
- Test: `suh-ai-server/flask/test/test_model_router.py`

**Interfaces:**
- Produces: `AuditCategory.MODEL`, `AuditAction.MODEL_DELETE / MODEL_DOWNLOAD / MODEL_DOWNLOAD_CANCEL` (Task 8 UI 라벨 매핑이 소비)

- [ ] **Step 1: 실패하는 테스트 작성** — `test/test_model_router.py`에 추가 (기존 client fixture 재사용):

```python
from service.audit_service import AuditAction, AuditCategory


def test_delete_model_records_audit(client, monkeypatch):
    calls = []
    monkeypatch.setattr('util.audit_helper.audit_service.record',
                        lambda *a, **k: calls.append((a, k)) or True)
    monkeypatch.setattr('router.model_router.model_service.delete_model', lambda name: None)
    resp = client.delete('/models/installed?name=llama3:8b')
    assert resp.status_code == 200
    (args, kwargs), = calls
    assert args[0] == AuditCategory.MODEL
    assert args[1] == AuditAction.MODEL_DELETE
    assert args[3] == {'name': 'llama3:8b'}


def test_enqueue_download_records_audit(client, monkeypatch):
    calls = []
    monkeypatch.setattr('util.audit_helper.audit_service.record',
                        lambda *a, **k: calls.append((a, k)) or True)
    monkeypatch.setattr('router.model_router.queue_service.enqueue', lambda name: None)
    monkeypatch.setattr('router.model_router.queue_service.get_state', lambda: {'items': []})
    resp = client.post('/models/queue', json={'name': 'qwen2.5:7b'})
    assert resp.status_code == 200
    (args, _), = calls
    assert args[1] == AuditAction.MODEL_DOWNLOAD
    assert args[3] == {'name': 'qwen2.5:7b'}


def test_cancel_download_records_audit(client, monkeypatch):
    calls = []
    monkeypatch.setattr('util.audit_helper.audit_service.record',
                        lambda *a, **k: calls.append((a, k)) or True)
    monkeypatch.setattr('router.model_router.queue_service.cancel', lambda item_id: 'removed')
    resp = client.delete('/models/queue/abc123')
    assert resp.status_code == 200
    (args, _), = calls
    assert args[1] == AuditAction.MODEL_DOWNLOAD_CANCEL
    assert args[3] == {'item_id': 'abc123', 'result': 'removed'}
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `cd suh-ai-server/flask && python3 -m pytest test/test_model_router.py -q`
Expected: 신규 3건 FAIL (`MODEL` 속성 없음)

- [ ] **Step 3: 구현** — `service/audit_service.py` enum에 추가:

```python
class AuditCategory(str, Enum):
    PALWORLD = "PALWORLD"
    TTS = "TTS"
    MODEL = "MODEL"
    SYSTEM = "SYSTEM"  # 향후 확장용
```

```python
    MODEL_DELETE = "MODEL_DELETE"
    MODEL_DOWNLOAD = "MODEL_DOWNLOAD"
    MODEL_DOWNLOAD_CANCEL = "MODEL_DOWNLOAD_CANCEL"
```

`router/model_router.py` — 임포트 추가 후 3개 엔드포인트에 부착:

```python
from service.audit_service import AuditCategory, AuditAction
from util.audit_helper import audited, set_audit_detail
```

```python
@model_bp.route('/models/installed', methods=['DELETE'])
@audited(AuditCategory.MODEL, AuditAction.MODEL_DELETE)
def delete_model():
    """설치된 모델 삭제 — 모델명에 /·:가 있어 query parameter 사용"""
    name = request.args.get('name', '').strip()
    if not name:
        return jsonify({'error': 'name query parameter is required'}), 400
    set_audit_detail({'name': name})
    ...(기존 로직 그대로)...


@model_bp.route('/models/queue', methods=['POST'])
@audited(AuditCategory.MODEL, AuditAction.MODEL_DOWNLOAD)
def enqueue_download():
    """모델 다운로드 큐 추가 — 워커가 순차 실행하므로 브라우저를 닫아도 진행된다"""
    ...(name 파싱 후)...
    set_audit_detail({'name': name})
    ...(기존 로직 그대로)...


@model_bp.route('/models/queue/<item_id>', methods=['DELETE'])
@audited(AuditCategory.MODEL, AuditAction.MODEL_DOWNLOAD_CANCEL)
def cancel_download(item_id):
    """대기 항목 제거 또는 진행 중 다운로드 취소"""
    set_audit_detail({'item_id': item_id})
    try:
        result = queue_service.cancel(item_id)
    except KeyError:
        return jsonify({'error': '해당 항목을 찾을 수 없습니다'}), 404
    set_audit_detail({'result': result})
    logger.info(f"Model queue cancel: {item_id} -> {result}")
    return jsonify({'success': True, 'result': result}), 200
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `cd suh-ai-server/flask && python3 -m pytest test/test_model_router.py test/test_audit_service.py -q`
Expected: 전체 PASS

- [ ] **Step 5: 커밋**

```bash
git add suh-ai-server/flask/service/audit_service.py suh-ai-server/flask/router/model_router.py suh-ai-server/flask/test/test_model_router.py
git commit -m "감사로그 전면 개선: 전용 페이지, 공통 데코레이터, 기록 보강 : feat : 모델 관리 감사 기록 추가(MODEL 카테고리) https://github.com/Cassiiopeia/suh-project-control/issues/104"
```

---

### Task 7: 조회 API `GET /audit/logs` + 페이지 라우트 + Swagger

**Files:**
- Create: `suh-ai-server/flask/router/audit_router.py`
- Create: `suh-ai-server/flask/router/audit_swagger.py`
- Modify: `suh-ai-server/flask/app.py` (블루프린트 등록)
- Modify: `suh-ai-server/flask/router/swagger_router.py` (paths 병합)
- Modify: `suh-ai-server/flask/router/admin_router.py` (/admin/audit 페이지)
- Test: `suh-ai-server/flask/test/test_audit_router.py`

**Interfaces:**
- Consumes: Task 2의 `query_logs()`
- Produces: `GET /audit/logs?category=&action=&success=&search=&limit=&before_id=` → `{'success': True, 'available': bool, 'location': str, 'rows': [...], 'has_more': bool}` (Task 8 audit.js가 소비), `GET /admin/audit` 페이지

- [ ] **Step 1: 실패하는 테스트 작성** — `test/test_audit_router.py` 생성:

```python
"""test_audit_router.py — 구조화 감사 조회 API"""
from unittest.mock import patch

import pytest
from flask import Flask

from router.audit_router import audit_bp

FAKE = {'available': True, 'location': 'postgresql://h:5430/db',
        'rows': [{'id': 1}], 'has_more': False}


@pytest.fixture
def client():
    app = Flask(__name__)
    app.register_blueprint(audit_bp)
    return app.test_client()


def test_audit_logs_passes_filters(client):
    with patch('router.audit_router.audit_service.query_logs', return_value=FAKE) as mock_q:
        resp = client.get('/audit/logs?category=TTS&action=TTS_START&success=true'
                          '&search=supertonic&limit=50&before_id=99')
    assert resp.status_code == 200
    mock_q.assert_called_once_with(category='TTS', action='TTS_START', success=True,
                                   search='supertonic', limit=50, before_id=99)
    data = resp.get_json()
    assert data['success'] is True
    assert data['rows'] == [{'id': 1}]


def test_audit_logs_defaults(client):
    with patch('router.audit_router.audit_service.query_logs', return_value=FAKE) as mock_q:
        resp = client.get('/audit/logs')
    assert resp.status_code == 200
    mock_q.assert_called_once_with(category=None, action=None, success=None,
                                   search=None, limit=100, before_id=None)


def test_audit_logs_rejects_bad_numbers(client):
    resp = client.get('/audit/logs?limit=abc')
    assert resp.status_code == 400
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `cd suh-ai-server/flask && python3 -m pytest test/test_audit_router.py -q`
Expected: FAIL (`No module named 'router.audit_router'`)

- [ ] **Step 3: 구현** — `router/audit_router.py` 생성:

```python
"""
감사로그 조회 라우터 — 전용 관리자 페이지(/admin/audit)용 구조화 API
기록은 util/audit_helper.py의 @audited가 담당하고 여기는 조회 전용이다.
"""
import logging

from flask import Blueprint, jsonify, request

from service import audit_service

logger = logging.getLogger(__name__)

audit_bp = Blueprint('audit', __name__)


@audit_bp.route('/audit/logs', methods=['GET'])
def audit_logs():
    """감사로그 구조화 조회 (필터 + 키셋 페이징, 최신순)"""
    try:
        limit = int(request.args.get('limit', 100))
        before_id = request.args.get('before_id')
        before_id = int(before_id) if before_id is not None else None
    except ValueError:
        return jsonify({'error': 'limit/before_id must be integers'}), 400
    success_raw = request.args.get('success')
    success = None
    if success_raw is not None and success_raw != '':
        success = success_raw.lower() in ('1', 'true', 'yes')
    result = audit_service.query_logs(
        category=request.args.get('category') or None,
        action=request.args.get('action') or None,
        success=success,
        search=request.args.get('search') or None,
        limit=limit,
        before_id=before_id,
    )
    return jsonify({'success': True, **result}), 200
```

`router/audit_swagger.py` 생성 (기존 `palworld_swagger.py` 패턴):

```python
"""Audit API swagger paths"""

AUDIT_SWAGGER_PATHS = {
    "/audit/logs": {
        "get": {
            "tags": ["Audit"],
            "summary": "관리 행위 감사로그 조회",
            "description": "카테고리/행위/성공여부/검색어 필터와 키셋 페이징(before_id)을 지원한다",
            "security": [{"ApiKeyAuth": []}],
            "parameters": [
                {"name": "category", "in": "query", "schema": {"type": "string"},
                 "description": "PALWORLD | TTS | MODEL | SYSTEM"},
                {"name": "action", "in": "query", "schema": {"type": "string"}},
                {"name": "success", "in": "query", "schema": {"type": "boolean"}},
                {"name": "search", "in": "query", "schema": {"type": "string"},
                 "description": "IP/행위/상세 부분 일치 검색"},
                {"name": "limit", "in": "query", "schema": {"type": "integer", "default": 100}},
                {"name": "before_id", "in": "query", "schema": {"type": "integer"},
                 "description": "이 id 미만 행 조회 (다음 페이지)"},
            ],
            "responses": {"200": {"description": "감사로그 행 목록"}},
        }
    }
}
```

`router/swagger_router.py` — 임포트 후 paths 병합 (`PALWORLD_SWAGGER_PATHS` 병합되는 위치와 같은 방식으로 `**AUDIT_SWAGGER_PATHS` 추가):

```python
from router.audit_swagger import AUDIT_SWAGGER_PATHS
```

`app.py` — 블루프린트 등록 (기존 register_blueprint 나열부에 추가):

```python
from router.audit_router import audit_bp
app.register_blueprint(audit_bp)
```

`router/admin_router.py` — 페이지 라우트 추가:

```python
@admin_bp.route('/admin/audit', methods=['GET'])
def audit():
    """관리 행위 감사로그 페이지"""
    return render_template('admin/audit.html', root='..', active='audit')
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `cd suh-ai-server/flask && python3 -m pytest test/test_audit_router.py test/test_admin_router.py -q`
Expected: 전체 PASS (test_admin_router가 페이지 목록을 검증한다면 audit 추가 반영)

- [ ] **Step 5: 커밋**

```bash
git add suh-ai-server/flask/router/audit_router.py suh-ai-server/flask/router/audit_swagger.py suh-ai-server/flask/router/swagger_router.py suh-ai-server/flask/app.py suh-ai-server/flask/router/admin_router.py suh-ai-server/flask/test/test_audit_router.py
git commit -m "감사로그 전면 개선: 전용 페이지, 공통 데코레이터, 기록 보강 : feat : 감사로그 조회 API 및 페이지 라우트 추가 https://github.com/Cassiiopeia/suh-project-control/issues/104"
```

---

### Task 8: 전용 UI — 네비 탭 + audit.html + audit.js

**Files:**
- Modify: `suh-ai-server/flask/templates/admin/base.html` (네비 탭)
- Create: `suh-ai-server/flask/templates/admin/audit.html`
- Create: `suh-ai-server/flask/static/js/audit.js`
- Build: `suh-ai-server/flask/frontend`에서 `npm run build` (CSS purge 재빌드)

**Interfaces:**
- Consumes: Task 7의 `GET /audit/logs` 응답 형식

- [ ] **Step 1: base.html 네비 탭 추가** — "Flask 로그" `<li>` 바로 위에 삽입:

```html
        <li>
          <a href="{{ root }}/admin/audit" class="{{ 'menu-active' if active == 'audit' else '' }}">
            <i data-lucide="shield-check" class="size-5"></i>감사로그
          </a>
        </li>
```

- [ ] **Step 2: audit.html 작성** — `templates/admin/audit.html` 생성:

```html
{% extends "admin/base.html" %}
{% block title %}감사로그 | SUH AI Server{% endblock %}
{% block page_title %}감사로그{% endblock %}
{% block content %}
<div class="card bg-base-100 shadow max-w-6xl mx-auto">
  <div class="card-body">
    <h2 class="card-title text-base">
      <i data-lucide="shield-check" class="size-5"></i>관리 행위 감사로그
    </h2>
    <div class="flex flex-wrap items-center gap-2 mb-2">
      <select id="audit-category" class="select select-sm w-32">
        <option value="">전체 서비스</option>
        <option value="PALWORLD">팰월드</option>
        <option value="TTS">TTS</option>
        <option value="MODEL">모델</option>
        <option value="SYSTEM">시스템</option>
      </select>
      <select id="audit-action" class="select select-sm w-48">
        <option value="">전체 행위</option>
      </select>
      <select id="audit-success" class="select select-sm w-28">
        <option value="">전체 결과</option>
        <option value="true">성공</option>
        <option value="false">실패</option>
      </select>
      <label class="input input-sm flex items-center gap-1 w-52">
        <i data-lucide="search" class="size-4 opacity-60"></i>
        <input type="text" id="audit-search" class="grow" placeholder="IP·상세 검색"
               autocomplete="off" spellcheck="false">
      </label>
      <label class="label cursor-pointer gap-2 text-sm">
        <input type="checkbox" id="audit-auto" class="toggle toggle-sm toggle-primary" checked>
        <span>자동 새로고침</span>
      </label>
      <button type="button" id="audit-refresh" class="btn btn-ghost btn-sm">
        <i data-lucide="refresh-cw" class="size-4"></i>새로고침
      </button>
    </div>
    <div class="flex items-center justify-between text-xs opacity-60 mb-2 gap-2">
      <span class="font-mono break-all" id="audit-meta"></span>
      <span id="audit-count" class="shrink-0"></span>
    </div>
    <div class="overflow-x-auto">
      <table class="table table-sm table-zebra">
        <thead>
          <tr>
            <th>시간 (KST)</th><th>서비스</th><th>행위</th>
            <th>실행 IP</th><th>결과</th><th></th>
          </tr>
        </thead>
        <tbody id="audit-rows"></tbody>
      </table>
    </div>
    <div class="text-center mt-2">
      <button type="button" id="audit-more" class="btn btn-ghost btn-sm hidden">더 보기</button>
    </div>
  </div>
</div>
{% endblock %}
{% block extra_js %}
<script src="{{ root }}/static/js/audit.js?v={{ asset('js/audit.js') }}"></script>
{% endblock %}
```

- [ ] **Step 3: audit.js 작성** — `static/js/audit.js` 생성:

```javascript
/* 감사로그 전용 페이지 — 구조화 테이블 + 필터 + 키셋 페이징 + 자동 새로고침(10초)
   행위 라벨은 여기서만 관리한다: AuditAction enum 추가 시 ACTION_LABELS에 한 줄 추가 (없으면 코드 원문 표시) */
(function () {
  var API = '../audit/logs';

  var CATEGORY_META = {
    PALWORLD: { label: '팰월드', badge: 'badge-primary' },
    TTS: { label: 'TTS', badge: 'badge-secondary' },
    MODEL: { label: '모델', badge: 'badge-accent' },
    SYSTEM: { label: '시스템', badge: 'badge-neutral' },
  };

  var ACTION_LABELS = {
    SERVER_START: '팰월드 서버 시작',
    SERVER_STOP: '팰월드 서버 중지',
    SERVER_RESTART: '팰월드 서버 재시작',
    SETTINGS_UPDATE: '팰월드 설정 변경',
    BACKUP_CREATE: '팰월드 백업 생성',
    SERVER_UPDATE: '팰월드 서버 업데이트',
    TTS_INSTALL: 'TTS 엔진 설치',
    TTS_START: 'TTS 엔진 시작',
    TTS_STOP: 'TTS 엔진 중지',
    TTS_VOICE_ADD: 'TTS 보이스 등록',
    TTS_VOICE_DELETE: 'TTS 보이스 삭제',
    MODEL_DELETE: '모델 삭제',
    MODEL_DOWNLOAD: '모델 다운로드',
    MODEL_DOWNLOAD_CANCEL: '모델 다운로드 취소',
  };

  // 카테고리 선택 시 행위 셀렉트를 해당 카테고리 것만으로 좁힌다
  var ACTIONS_BY_CATEGORY = {
    PALWORLD: ['SERVER_START', 'SERVER_STOP', 'SERVER_RESTART', 'SETTINGS_UPDATE',
               'BACKUP_CREATE', 'SERVER_UPDATE'],
    TTS: ['TTS_INSTALL', 'TTS_START', 'TTS_STOP', 'TTS_VOICE_ADD', 'TTS_VOICE_DELETE'],
    MODEL: ['MODEL_DELETE', 'MODEL_DOWNLOAD', 'MODEL_DOWNLOAD_CANCEL'],
    SYSTEM: [],
  };

  var KST_FMT = new Intl.DateTimeFormat('ko-KR', {
    timeZone: 'Asia/Seoul', month: '2-digit', day: '2-digit',
    hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false,
  });
  var KST_FULL = new Intl.DateTimeFormat('ko-KR', {
    timeZone: 'Asia/Seoul', year: 'numeric', month: '2-digit', day: '2-digit',
    hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false,
  });

  var rowsEl = document.getElementById('audit-rows');
  var metaEl = document.getElementById('audit-meta');
  var countEl = document.getElementById('audit-count');
  var moreBtn = document.getElementById('audit-more');
  var lastId = null;     // 키셋 페이징 커서 (표시 중인 가장 오래된 id)
  var shownCount = 0;

  function filters() {
    return {
      category: document.getElementById('audit-category').value,
      action: document.getElementById('audit-action').value,
      success: document.getElementById('audit-success').value,
      search: document.getElementById('audit-search').value.trim(),
    };
  }

  function buildUrl(beforeId) {
    var f = filters();
    var params = new URLSearchParams({ limit: '100' });
    if (f.category) params.set('category', f.category);
    if (f.action) params.set('action', f.action);
    if (f.success) params.set('success', f.success);
    if (f.search) params.set('search', f.search);
    if (beforeId) params.set('before_id', String(beforeId));
    return API + '?' + params.toString();
  }

  function syncActionOptions() {
    var category = document.getElementById('audit-category').value;
    var actionEl = document.getElementById('audit-action');
    var keys = category ? (ACTIONS_BY_CATEGORY[category] || []) : Object.keys(ACTION_LABELS);
    actionEl.innerHTML = '<option value="">전체 행위</option>' + keys.map(function (k) {
      return '<option value="' + k + '">' + (ACTION_LABELS[k] || k) + '</option>';
    }).join('');
  }

  function actionLabel(row) {
    var label = ACTION_LABELS[row.action] || row.action;  // 미등록 action은 코드 원문
    var d = row.detail || {};
    var suffix = d.engine || d.name || d.voice_id || null;
    return suffix ? label + ' (' + suffix + ')' : label;
  }

  function detailHtml(detail) {
    if (detail && typeof detail === 'object' && detail.changed &&
        typeof detail.changed === 'object') {
      // 설정 diff는 key: from → to 목록으로
      var items = Object.keys(detail.changed).map(function (key) {
        var v = detail.changed[key] || {};
        var from = (v && typeof v === 'object') ? v.from : '';
        var to = (v && typeof v === 'object') ? v.to : v;
        return '<div class="font-mono text-xs">' + escapeHtml(key) + ': ' +
          escapeHtml(String(from)) + ' → ' + escapeHtml(String(to)) + '</div>';
      }).join('');
      var applied = detail.applied === false
        ? '<div class="text-xs opacity-60 mt-1">재시작/중지 시 적용 예정(pending)</div>' : '';
      return items + applied;
    }
    return '<pre class="text-xs whitespace-pre-wrap">' +
      escapeHtml(JSON.stringify(detail, null, 2)) + '</pre>';
  }

  function appendRows(rows) {
    rows.forEach(function (row) {
      var cat = CATEGORY_META[row.category] || { label: row.category, badge: 'badge-ghost' };
      var when = new Date(row.occurred_at);
      var tr = document.createElement('tr');
      var proxyTip = (row.proxy_chain && row.proxy_chain.length)
        ? '경유: ' + row.proxy_chain.join(' → ') : '';
      var uaTip = row.user_agent ? 'UA: ' + row.user_agent : '';
      var ipTitle = [proxyTip, uaTip].filter(Boolean).join('\n');
      tr.innerHTML =
        '<td class="whitespace-nowrap font-mono text-xs" title="' +
          escapeHtml(KST_FULL.format(when)) + '">' + escapeHtml(KST_FMT.format(when)) + '</td>' +
        '<td><span class="badge badge-sm ' + cat.badge + '">' + escapeHtml(cat.label) + '</span></td>' +
        '<td>' + escapeHtml(actionLabel(row)) + '</td>' +
        '<td class="font-mono text-xs" title="' + escapeHtml(ipTitle) + '">' +
          escapeHtml(row.client_ip || '-') +
          (ipTitle ? ' <i data-lucide="info" class="size-3 inline opacity-50"></i>' : '') + '</td>' +
        '<td>' + (row.success
          ? '<span class="badge badge-sm badge-success">성공</span>'
          : '<span class="badge badge-sm badge-error">실패</span>') + '</td>' +
        '<td class="text-right">' + (row.detail
          ? '<button type="button" class="btn btn-ghost btn-xs" data-role="toggle">상세</button>'
          : '') + '</td>';
      rowsEl.appendChild(tr);
      if (row.detail) {
        var detailTr = document.createElement('tr');
        detailTr.className = 'hidden';
        var td = document.createElement('td');
        td.colSpan = 6;
        td.className = 'bg-base-200';
        td.innerHTML = detailHtml(row.detail);
        detailTr.appendChild(td);
        rowsEl.appendChild(detailTr);
        tr.querySelector('[data-role="toggle"]').addEventListener('click', function () {
          detailTr.classList.toggle('hidden');
        });
        tr.classList.add('cursor-pointer');
        tr.addEventListener('click', function (e) {
          if (e.target.closest('button')) return;  // 버튼 클릭과 중복 토글 방지
          detailTr.classList.toggle('hidden');
        });
      }
      lastId = row.id;
      shownCount++;
    });
  }

  async function load(more) {
    var resp;
    try {
      resp = await apiFetch(buildUrl(more ? lastId : null));
    } catch (e) { return; /* 401은 apiFetch가 modal 처리 */ }
    var data = await resp.json();
    if (!more) { rowsEl.innerHTML = ''; lastId = null; shownCount = 0; }
    if (data.available === false) {
      metaEl.textContent = '';
      countEl.textContent = '';
      rowsEl.innerHTML = '<tr><td colspan="6" class="text-center opacity-60">' +
        '감사 DB에 연결할 수 없습니다: ' + escapeHtml(data.location || '') + '</td></tr>';
      moreBtn.classList.add('hidden');
      return;
    }
    appendRows(data.rows || []);
    if (!shownCount) {
      rowsEl.innerHTML = '<tr><td colspan="6" class="text-center opacity-60">' +
        '조건에 맞는 감사로그가 없습니다</td></tr>';
    }
    metaEl.textContent = data.location || '';
    countEl.textContent = shownCount + '건 표시' + (data.has_more ? ' (더 있음)' : '');
    moreBtn.classList.toggle('hidden', !data.has_more);
    if (window.lucide) lucide.createIcons();
  }

  document.getElementById('audit-category').addEventListener('change', function () {
    syncActionOptions(); load(false);
  });
  document.getElementById('audit-action').addEventListener('change', function () { load(false); });
  document.getElementById('audit-success').addEventListener('change', function () { load(false); });
  document.getElementById('audit-search').addEventListener('change', function () { load(false); });
  document.getElementById('audit-refresh').addEventListener('click', function () { load(false); });
  moreBtn.addEventListener('click', function () { load(true); });

  setInterval(function () {
    // 페이징으로 과거를 보는 중이면 자동 새로고침이 목록을 리셋하지 않게 첫 페이지일 때만
    if (document.getElementById('audit-auto').checked && !document.hidden && shownCount <= 100) {
      load(false);
    }
  }, 10000);

  document.addEventListener('DOMContentLoaded', function () {
    syncActionOptions();
    load(false);
  });
})();
```

- [ ] **Step 4: CSS 재빌드** — 새 클래스(table-zebra, badge-success 등) purge 방지:

Run: `cd suh-ai-server/flask/frontend && npm run build`
Expected: `../static/css/app.css` 갱신 (에러 없음)

- [ ] **Step 5: 수동 검증** — Flask 로컬 기동 없이 문법만 확인:

Run: `cd suh-ai-server/flask && python3 -c "import app" 2>&1 | tail -1; node --check static/js/audit.js && echo JS-OK`
Expected: `JS-OK` (app import는 의존성 없으면 경고만 — 에러 아니면 통과)

- [ ] **Step 6: 커밋**

```bash
git add suh-ai-server/flask/templates/admin/base.html suh-ai-server/flask/templates/admin/audit.html suh-ai-server/flask/static/js/audit.js suh-ai-server/flask/static/css/app.css
git commit -m "감사로그 전면 개선: 전용 페이지, 공통 데코레이터, 기록 보강 : feat : 감사로그 전용 페이지 UI(테이블·필터·페이징) https://github.com/Cassiiopeia/suh-project-control/issues/104"
```

---

### Task 9: 팰월드 페이지 감사 탭 제거 + 전용 페이지 링크

**Files:**
- Modify: `suh-ai-server/flask/static/js/palworld.js` (sources에서 audit 제거)
- Modify: `suh-ai-server/flask/templates/admin/palworld.html` (링크 추가)

**Interfaces:**
- 유지: `GET /palworld/logs?source=audit`는 API 하위호환으로 남긴다 (UI 탭만 제거)

- [ ] **Step 1: palworld.js 수정** — `initLogViewer()` sources에서 감사 항목 삭제:

```javascript
    sources: [
      { id: 'game', label: '게임 로그' },
      { id: 'events', label: '이벤트' },
      { id: 'update', label: '업데이트' },
      { id: 'stderr', label: '오류(stderr)' },
      { id: 'flask', label: '시스템(Flask)' },
    ],
```

- [ ] **Step 2: palworld.html 로그 탭에 링크 추가** — `<div id="palworld-log-viewer"></div>` 바로 위에:

```html
      <div class="text-xs mb-2">
        <a href="{{ root }}/admin/audit" class="link link-primary inline-flex items-center gap-1">
          <i data-lucide="shield-check" class="size-3.5"></i>관리 행위 감사로그는 전용 페이지에서 확인
        </a>
      </div>
```

- [ ] **Step 3: 문법 확인**

Run: `node --check suh-ai-server/flask/static/js/palworld.js && echo JS-OK`
Expected: `JS-OK`

- [ ] **Step 4: 커밋**

```bash
git add suh-ai-server/flask/static/js/palworld.js suh-ai-server/flask/templates/admin/palworld.html
git commit -m "감사로그 전면 개선: 전용 페이지, 공통 데코레이터, 기록 보강 : feat : 팰월드 감사 탭 제거 및 전용 페이지 링크 https://github.com/Cassiiopeia/suh-project-control/issues/104"
```

---

### Task 10: 에이전트 가드레일 문서 + 전체 검증

**Files:**
- Create: `suh-ai-server/flask/CLAUDE.md`
- Test: 전체 스위트

- [ ] **Step 1: CLAUDE.md 작성** — `suh-ai-server/flask/CLAUDE.md` 생성:

```markdown
# suh-ai-server/flask 작업 규칙

## 감사로그 (필수)

**상태를 변경하는 관리 엔드포인트(POST/PUT/DELETE)를 추가하면 반드시 `@audited` 데코레이터를 부착한다.**
조회(GET)와 일반 사용 API(예: `POST /tts` 합성)는 감사 대상이 아니다.

### 사용법 (`util/audit_helper.py`)

```python
from service.audit_service import AuditCategory, AuditAction
from util.audit_helper import audited, set_audit_detail, set_audit_action, skip_audit

@bp.route('/example', methods=['POST'])
@audited(AuditCategory.PALWORLD, AuditAction.SERVER_START)
def example():
    set_audit_detail({'name': '...'})   # 선택: 상세 정보 병합 (여러 번 호출 가능)
    ...
```

- IP(XFF 분해)·User-Agent·성공/실패(status < 400)는 데코레이터가 자동 수집·판정한다.
- 액션이 런타임에 정해지면 `@audited(카테고리)`만 달고 검증 통과 직후 `set_audit_action()` 호출.
  action 미지정 상태로 끝나면 기록되지 않는다 (검증 실패 404 등은 감사 대상 아님).
- 의미 없는 기록(예: 실변경 없는 설정 저장)은 `skip_audit()`로 생략한다.
- 요청 컨텍스트 밖(백그라운드 스레드)은 `audit_service.record()`를 직접 호출한다 (예: `palworld_updater`).

### 새 카테고리/행위 추가 절차 (마이그레이션 불필요)

1. `service/audit_service.py`의 `AuditCategory`/`AuditAction` enum에 값 추가
2. `static/js/audit.js`의 `ACTION_LABELS`와 `ACTIONS_BY_CATEGORY`에 한국어 라벨 추가
   (라벨이 없어도 UI는 enum 코드 원문으로 표시되어 깨지지 않는다)
3. 카테고리 추가 시 `audit.js`의 `CATEGORY_META`와 `templates/admin/audit.html`의
   카테고리 셀렉트 옵션에도 추가

### 정책

- fail-open: 감사 DB 다운/URL 미설정이 관리 행위를 절대 막지 않는다
- `audit_log.actor_ip`(XFF 원문)는 감사 원본이므로 삭제/변경 금지
- 실패한 관리 행위 시도도 `success=false`로 기록된다

## 프론트 CSS

`static/css/app.css`는 Tailwind 4 + daisyUI 빌드 산출물(purge)이다.
템플릿/JS에서 새 클래스를 쓰면 `frontend/`에서 `npm run build`로 재빌드해 함께 커밋한다.

## 테스트

`suh-ai-server/flask`에서 `python3 -m pytest test/ -q`
```

- [ ] **Step 2: 전체 테스트 실행**

Run: `cd suh-ai-server/flask && python3 -m pytest test/ -q`
Expected: 전체 PASS (깨진 테스트가 있으면 이 태스크에서 수정)

- [ ] **Step 3: 커밋**

```bash
git add suh-ai-server/flask/CLAUDE.md
git commit -m "감사로그 전면 개선: 전용 페이지, 공통 데코레이터, 기록 보강 : docs : 감사로그 가드레일 CLAUDE.md 추가 https://github.com/Cassiiopeia/suh-project-control/issues/104"
```

---

## 계획 셀프 리뷰 결과

- 스펙 §1~§7 전 항목이 Task 1~10에 매핑됨 (§1→T3~5, §2→T1, §3→T6, §4→T2·T7, §5→T8·T9, §6→T10, §7→각 태스크 테스트 스텝)
- `record()` 시그니처·`query_logs` 반환 형식·API 응답 필드가 태스크 간 일치함을 확인
- 플레이스홀더 없음 — 단, Task 4·5의 "기존 로직 그대로" 부분은 해당 파일의 현재 코드를 유지하라는 지시(전체 코드는 파일에 이미 존재)
```
