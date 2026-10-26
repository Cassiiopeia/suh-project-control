"""test_claude_login_code_service.py — 코드 작업 상태·만료·감사·열람 중복 제거"""
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

from service import claude_login_code_service as code_service
from service.audit_service import AuditAction
from service.claude_login_browser_client import BrowserClientError, LoginCodeNotFoundError
from service.claude_login_mail_client import MagicLinkMail, MailClientError

START_TIME = datetime(2026, 10, 26, 0, 34, 0, tzinfo=timezone.utc)
MAIL_TIME = START_TIME + timedelta(seconds=20)
CLIENT = {'actor_ip': '1.2.3.4', 'client_ip': '1.2.3.4', 'proxy_chain': [], 'user_agent': 'UA'}
MAIL = MagicLinkMail('<m1@anthropic>', MAIL_TIME, 'https://claude.ai/magic-link#t')


@pytest.fixture(autouse=True)
def configured_service(monkeypatch):
    monkeypatch.setenv('CLAUDE_LOGIN_GMAIL_ADDRESS', 'me@gmail.com')
    monkeypatch.setenv('CLAUDE_LOGIN_GMAIL_APP_PASSWORD', 'app-password')
    code_service._reset_for_test()
    with patch.object(code_service, '_now', return_value=START_TIME), \
            patch.object(code_service, '_sleep'):
        yield


def run_job(find_mail=None, read_code=None):
    """동기 실행 + audit_service.record 호출 목록 반환"""
    with patch.object(code_service, 'find_new_magic_link_mail', find_mail or (lambda *a, **k: MAIL)), \
            patch.object(code_service, 'read_login_code', read_code or (lambda *a, **k: '027696')), \
            patch.object(code_service.audit_service, 'record') as record:
        state, is_new_job = code_service.start_request('auto', CLIENT, run_in_thread=False)
    return state, is_new_job, record


def test_issued_flow_sets_code_and_mail_time():
    run_job()
    state = code_service.get_state(now=MAIL_TIME + timedelta(seconds=30))
    assert state['status'] == 'issued'
    assert state['step'] == 'issued'
    assert state['code'] == '027696'
    assert state['mail_received_at'] == MAIL_TIME.isoformat()
    assert state['expires_at'] == (MAIL_TIME + timedelta(seconds=600)).isoformat()
    assert state['account'] == 'me@gmail.com'


def test_second_request_while_running_returns_same_job():
    with patch.object(code_service.threading, 'Thread'):
        first_state, is_first_new = code_service.start_request('auto', CLIENT)
        second_state, is_second_new = code_service.start_request('manual', CLIENT)
    assert is_first_new is True
    assert is_second_new is False
    assert second_state['job_id'] == first_state['job_id']
    assert second_state['status'] == 'running'


def test_accept_after_is_start_minus_120_seconds():
    received_arguments = []

    def find_mail(address, app_password, accept_after, processed_message_ids):
        received_arguments.append(accept_after)
        return MAIL
    run_job(find_mail=find_mail)
    assert received_arguments[0] == START_TIME - timedelta(seconds=120)


def test_timeout_sets_failed_timeout():
    times = iter([START_TIME, START_TIME, START_TIME + timedelta(seconds=601)])
    with patch.object(code_service, '_now', side_effect=lambda: next(times, START_TIME + timedelta(seconds=700))):
        _, _, record = run_job(find_mail=lambda *a, **k: None)
    state = code_service.get_state(now=START_TIME + timedelta(seconds=700))
    assert state['status'] == 'failed'
    assert state['failure_reason'] == 'timeout'
    assert record.call_args.kwargs['success'] is False


def test_mail_error_sets_failed_state():
    def find_mail(*args, **kwargs):
        raise MailClientError('imap login failed')
    _, _, record = run_job(find_mail=find_mail)
    state = code_service.get_state()
    assert state['status'] == 'failed'
    assert state['failure_reason'] == 'mail_error'
    assert record.call_args.args[1] == AuditAction.CLAUDE_CODE_ISSUED
    assert record.call_args.kwargs['success'] is False


def test_code_not_found_sets_screenshot_flag():
    def read_code(*args, **kwargs):
        raise LoginCodeNotFoundError('login code not found')
    run_job(read_code=read_code)
    state = code_service.get_state()
    assert state['failure_reason'] == 'code_not_found'
    assert state['has_screenshot'] is True


def test_browser_error_sets_failed_state():
    def read_code(*args, **kwargs):
        raise BrowserClientError('browser failed')
    run_job(read_code=read_code)
    assert code_service.get_state()['failure_reason'] == 'browser_error'


def test_processed_mail_not_reopened_after_failure():
    seen_processed = []

    def read_code(*args, **kwargs):
        raise LoginCodeNotFoundError('x')
    run_job(read_code=read_code)

    def find_mail(address, app_password, accept_after, processed_message_ids):
        seen_processed.append(set(processed_message_ids))
        return MAIL
    run_job(find_mail=find_mail)
    assert '<m1@anthropic>' in seen_processed[0]


def test_code_hidden_after_link_expiry():
    run_job()
    state = code_service.get_state(now=MAIL_TIME + timedelta(seconds=601))
    assert state['code'] is None
    assert state['status'] == 'expired'


def test_view_recorded_once_per_ip():
    run_job()
    job_id = code_service.get_state()['job_id']
    assert code_service.should_record_view(job_id, '1.2.3.4') is True
    assert code_service.should_record_view(job_id, '1.2.3.4') is False
    assert code_service.should_record_view(job_id, '5.6.7.8') is True


def test_issued_audit_detail_excludes_code():
    _, _, record = run_job()
    assert record.call_count == 1
    assert record.call_args.args[1] == AuditAction.CLAUDE_CODE_ISSUED
    assert record.call_args.kwargs['success'] is True
    assert '027696' not in repr(record.call_args)


def test_start_without_config_raises_not_configured(monkeypatch):
    monkeypatch.delenv('CLAUDE_LOGIN_GMAIL_APP_PASSWORD')
    with pytest.raises(code_service.NotConfiguredError):
        code_service.start_request('auto', CLIENT, run_in_thread=False)
    assert code_service.get_state()['is_configured'] is False
