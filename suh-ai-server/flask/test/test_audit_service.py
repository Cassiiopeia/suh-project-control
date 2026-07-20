"""test_audit_service.py"""
from datetime import datetime
from unittest.mock import patch, MagicMock

from service.audit_service import (
    AuditCategory, AuditAction, record, list_logs, query_logs, _format_line, _masked_location,
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


def test_list_logs_fail_open_on_db_error(monkeypatch):
    monkeypatch.setenv('AUDIT_DATABASE_URL', URL)
    with patch('service.audit_service.psycopg2.connect', side_effect=Exception('down')):
        result = list_logs(100)
    assert result['exists'] is False


# --- query_logs ---

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


def test_query_logs_fail_open_on_db_error(monkeypatch):
    monkeypatch.setenv('AUDIT_DATABASE_URL', URL)
    with patch('service.audit_service.psycopg2.connect', side_effect=Exception('down')):
        result = query_logs()
    assert result['available'] is False


# --- 헬퍼 ---

def test_format_line_settings_update_shows_diff():
    line = _format_line(datetime(2026, 7, 14, 15, 0, 0), '1.2.3.4', 'SETTINGS_UPDATE',
                        {'changed': {'ExpRate': {'from': '2.0', 'to': '3.0'}}}, category='PALWORLD')
    assert '1.2.3.4' in line
    assert 'ExpRate: 2.0 → 3.0' in line


def test_format_line_includes_category_and_engine():
    line = _format_line(datetime(2026, 7, 19, 6, 17, 9), '14.63.73.230', 'TTS_START',
                        {'engine': 'supertonic'}, category='TTS')
    assert 'TTS/TTS_START' in line
    assert 'supertonic' in line


def test_masked_location_strips_credentials():
    masked = _masked_location(URL)
    assert masked == 'postgresql://suh-project.synology.me:5430/suh_ai_server'


def test_format_line_survives_malformed_changed_value():
    line = _format_line(datetime(2026, 7, 15, 10, 0, 0), '1.2.3.4', 'SETTINGS_UPDATE',
                        {'changed': {'ExpRate': 'not-a-dict'}})
    assert 'ExpRate: not-a-dict' in line  # 예외 없이 원값 표시
