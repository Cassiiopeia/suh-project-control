"""test_audit_retention_service.py"""
from unittest.mock import patch, MagicMock

from service import audit_retention_service
from service.audit_retention_service import (
    AUDIT_LOG_RETENTION_DAYS, purge_expired_audit_logs, run_retention_loop,
)

URL = 'postgresql://user:secret@suh-project.synology.me:5430/suh_ai_server'


def _mock_conn(deleted_row_count=0):
    conn = MagicMock()
    cursor = MagicMock()
    cursor.rowcount = deleted_row_count
    conn.cursor.return_value.__enter__ = MagicMock(return_value=cursor)
    conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
    conn.__enter__ = MagicMock(return_value=conn)
    conn.__exit__ = MagicMock(return_value=False)
    return conn, cursor


def test_purge_returns_none_without_url(monkeypatch):
    # URL 미설정 = 감사로그 미사용 환경, 아무것도 하지 않음
    monkeypatch.delenv('AUDIT_DATABASE_URL', raising=False)
    assert purge_expired_audit_logs() is None


def test_purge_deletes_rows_older_than_retention(monkeypatch):
    monkeypatch.setenv('AUDIT_DATABASE_URL', URL)
    conn, cursor = _mock_conn(deleted_row_count=7)
    with patch('service.audit_retention_service.psycopg2.connect', return_value=conn):
        assert purge_expired_audit_logs() == 7
    sql, params = cursor.execute.call_args[0]
    assert 'DELETE FROM audit_log' in sql
    assert 'occurred_at <' in sql
    assert params == (AUDIT_LOG_RETENTION_DAYS,)
    conn.close.assert_called_once()


def test_purge_returns_none_when_db_fails(monkeypatch):
    # fail-open: DB 오류가 서버 기동·다른 기능을 막지 않는다
    monkeypatch.setenv('AUDIT_DATABASE_URL', URL)
    with patch('service.audit_retention_service.psycopg2.connect', side_effect=RuntimeError('db down')):
        assert purge_expired_audit_logs() is None


def test_retention_period_is_one_year():
    assert AUDIT_LOG_RETENTION_DAYS == 365


def test_loop_purges_every_interval_and_survives_failure():
    stop_event = MagicMock()
    # 3번째 대기에서 종료 신호
    stop_event.wait.side_effect = [False, False, True]
    purge_results = [3, RuntimeError('boom'), 0]

    def fake_purge():
        result = purge_results.pop(0)
        if isinstance(result, Exception):
            raise result
        return result

    with patch.object(audit_retention_service, 'purge_expired_audit_logs', side_effect=fake_purge) as purge_mock:
        run_retention_loop(stop_event)
    # 첫 대기 후 1회, 둘째 대기 후 예외(무시), 셋째 대기에서 종료 = 총 2회 호출
    assert purge_mock.call_count == 2
