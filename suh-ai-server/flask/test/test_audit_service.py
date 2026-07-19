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


def test_format_line_survives_malformed_changed_value():
    line = _format_line(datetime(2026, 7, 15, 10, 0, 0), '1.2.3.4', 'SETTINGS_UPDATE',
                        {'changed': {'ExpRate': 'not-a-dict'}})
    assert 'ExpRate: not-a-dict' in line  # 예외 없이 원값 표시
