"""test_claude_login_code_service.py — 계정별 코드 작업 상태·만료·감사·열람 중복 제거·동시 계정"""
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock, patch

import pytest

from service import claude_login_code_service as code_service
from service.audit_service import AuditAction
from service.claude_login_account_repository import ClaudeLoginAccount
from service.claude_login_account_service import AccountCredential, AccountNotFoundError
from service.claude_login_browser_client import BrowserClientError, LoginCodeNotFoundError
from service.claude_login_mail_client import MagicLinkMail, MailClientError
from service.claude_login_secret_cipher import SecretCipherError

START_TIME = datetime(2026, 10, 26, 0, 34, 0, tzinfo=timezone.utc)
MAIL_TIME = START_TIME + timedelta(seconds=20)
CLIENT = {'actor_ip': '1.2.3.4', 'client_ip': '1.2.3.4', 'proxy_chain': [], 'user_agent': 'UA'}
MAIL = MagicLinkMail('<m1@anthropic>', MAIL_TIME, 'https://claude.ai/magic-link#t')


def build_account(account_id, address, is_enabled=True):
    return ClaudeLoginAccount(account_id, address, f'계정{account_id}', b'x', 'pbkdf2-aes256gcm-v1',
                              is_enabled, None, False, START_TIME, START_TIME)


ACCOUNTS = {1: build_account(1, 'me@gmail.com'), 2: build_account(2, 'work@gmail.com'),
            3: build_account(3, 'off@gmail.com', is_enabled=False)}


@pytest.fixture(autouse=True)
def configured_service():
    code_service._reset_for_test()
    repository = code_service.account_repository
    with patch.object(code_service, '_now', return_value=START_TIME), \
            patch.object(code_service, '_sleep'), \
            patch.object(repository, 'list_accounts',
                         lambda is_enabled_only=False: [a for a in ACCOUNTS.values() if a.is_enabled or not is_enabled_only]), \
            patch.object(repository, 'find_account', lambda account_id: ACCOUNTS.get(account_id)), \
            patch.object(repository, 'mark_success') as mark_success, \
            patch.object(code_service.account_service, 'load_credential',
                         lambda account: AccountCredential(account.id, account.gmail_address,
                                                           account.display_name, 'app-password')):
        yield mark_success


def run_job(find_mail=None, read_code=None, account_id=1, trigger='auto'):
    """동기 실행 + audit_service.record 호출 목록 반환"""
    with patch.object(code_service, 'find_new_magic_link_mail', find_mail or (lambda *a, **k: MAIL)), \
            patch.object(code_service, 'read_login_code', read_code or (lambda *a, **k: '027696')), \
            patch.object(code_service.audit_service, 'record') as record:
        results = code_service.start_requests(trigger, CLIENT, account_id, run_in_thread=False)
    return results, record


def test_issued_flow_sets_code_and_mail_time(configured_service):
    run_job()
    state = code_service.get_state(1, now=MAIL_TIME + timedelta(seconds=30))
    assert state['status'] == 'issued'
    assert state['code'] == '027696'
    assert state['mail_received_at'] == MAIL_TIME.isoformat()
    assert state['expires_at'] == (MAIL_TIME + timedelta(seconds=600)).isoformat()
    assert state['gmail_address'] == 'me@gmail.com'
    configured_service.assert_called_once_with(1)


def test_start_without_account_id_starts_enabled_accounts_only():
    with patch.object(code_service.threading, 'Thread'):
        results = code_service.start_requests('auto', CLIENT)
    assert sorted(state['account_id'] for state, _ in results) == [1, 2]
    assert all(is_new for _, is_new in results)


def test_accounts_have_independent_states():
    run_job(account_id=1)

    def failing(*args, **kwargs):
        raise MailClientError('imap login failed')
    run_job(find_mail=failing, account_id=2)
    assert code_service.get_state(1)['status'] == 'issued'
    assert code_service.get_state(2)['failure_reason'] == 'mail_error'


def test_second_request_while_running_returns_same_job():
    with patch.object(code_service.threading, 'Thread'):
        [(first_state, is_first_new)] = code_service.start_requests('auto', CLIENT, 1)
        [(second_state, is_second_new)] = code_service.start_requests('manual', CLIENT, 1)
    assert is_first_new is True
    assert is_second_new is False
    assert second_state['job_id'] == first_state['job_id']


def test_unknown_account_raises_not_found():
    with pytest.raises(AccountNotFoundError):
        code_service.start_requests('manual', CLIENT, 99)


def test_accept_after_is_start_minus_120_seconds():
    received_arguments = []

    def find_mail(address, app_password, accept_after, processed_message_ids):
        received_arguments.append((address, accept_after))
        return MAIL
    run_job(find_mail=find_mail)
    assert received_arguments[0] == ('me@gmail.com', START_TIME - timedelta(seconds=120))


def test_timeout_sets_failed_timeout():
    times = iter([START_TIME, START_TIME, START_TIME + timedelta(seconds=601)])
    with patch.object(code_service, '_now', side_effect=lambda: next(times, START_TIME + timedelta(seconds=700))):
        _, record = run_job(find_mail=lambda *a, **k: None)
    state = code_service.get_state(1, now=START_TIME + timedelta(seconds=700))
    assert state['failure_reason'] == 'timeout'
    assert record.call_args.kwargs['success'] is False


def test_decrypt_error_sets_failed_state():
    with patch.object(code_service.account_service, 'load_credential', side_effect=SecretCipherError('x')):
        run_job()
    assert code_service.get_state(1)['failure_reason'] == 'decrypt_error'


def test_code_not_found_sets_screenshot_flag_and_account_path():
    paths = []

    def read_code(magic_link, screenshot_path):
        paths.append(screenshot_path)
        raise LoginCodeNotFoundError('login code not found')
    run_job(read_code=read_code, account_id=2)
    state = code_service.get_state(2)
    assert state['failure_reason'] == 'code_not_found'
    assert state['has_screenshot'] is True
    assert paths[0].endswith('claude_login_failure_2.png')


def test_browser_error_sets_failed_state():
    def read_code(*args, **kwargs):
        raise BrowserClientError('browser failed')
    run_job(read_code=read_code)
    assert code_service.get_state(1)['failure_reason'] == 'browser_error'


def test_processed_mail_is_tracked_per_account():
    seen_processed = {}

    def read_code(*args, **kwargs):
        raise LoginCodeNotFoundError('x')
    run_job(read_code=read_code, account_id=1)

    def find_mail(address, app_password, accept_after, processed_message_ids):
        seen_processed[address] = set(processed_message_ids)
        return MAIL
    run_job(find_mail=find_mail, account_id=1, trigger='manual')
    run_job(find_mail=find_mail, account_id=2)
    assert '<m1@anthropic>' in seen_processed['me@gmail.com']
    assert seen_processed['work@gmail.com'] == set()


def test_code_hidden_after_link_expiry():
    run_job()
    state = code_service.get_state(1, now=MAIL_TIME + timedelta(seconds=601))
    assert state['code'] is None
    assert state['status'] == 'expired'


def test_get_states_lists_enabled_and_idle_accounts():
    run_job(account_id=1)
    states = code_service.get_states(now=MAIL_TIME)
    by_id = {state['account_id']: state for state in states}
    assert set(by_id) == {1, 2}
    assert by_id[1]['status'] == 'issued'
    assert by_id[2]['status'] == 'idle'


def test_view_recorded_once_per_ip():
    run_job()
    job_id = code_service.get_state(1)['job_id']
    assert code_service.should_record_view(job_id, '1.2.3.4') is True
    assert code_service.should_record_view(job_id, '1.2.3.4') is False
    assert code_service.should_record_view(job_id, '5.6.7.8') is True


def test_issued_audit_detail_has_account_and_excludes_code_and_password():
    _, record = run_job()
    assert record.call_count == 1
    assert record.call_args.args[1] == AuditAction.CLAUDE_CODE_ISSUED
    assert record.call_args.args[3]['account_id'] == 1
    assert '027696' not in repr(record.call_args)
    assert 'app-password' not in repr(record.call_args)


def test_auto_request_keeps_valid_issued_code():
    run_job()
    with patch.object(code_service, '_now', return_value=MAIL_TIME + timedelta(seconds=60)):
        [(state, is_new_job)] = code_service.start_requests('auto', CLIENT, 1, run_in_thread=False)
    assert is_new_job is False
    assert state['code'] == '027696'


def test_manual_request_replaces_issued_code():
    run_job()
    with patch.object(code_service.threading, 'Thread'):
        [(state, is_new_job)] = code_service.start_requests('manual', CLIENT, 1)
    assert is_new_job is True
    assert state['status'] == 'running'


SENDER = 'service.claude_login_code_service.send_project_event'


def test_issued_sends_project_event_without_code_or_address():
    with patch(SENDER) as send:
        run_job()
    assert send.call_count == 1
    assert send.call_args.args[:3] == ('suh-ai', 'claude-code', 'Claude 코드 발급')
    fields = dict(send.call_args.kwargs['fields'])
    assert fields == {'계정': '계정1', 'IP': '1.2.3.4', '브라우저': 'UA'}
    assert send.call_args.kwargs['dedupe_key'] == f"claude-code:issued:{code_service.get_state(1)['job_id']}"
    assert '027696' not in repr(send.call_args)
    assert 'me@gmail.com' not in repr(send.call_args)


def test_failed_job_sends_no_project_event():
    with patch(SENDER) as send:
        run_job(read_code=Mock(side_effect=BrowserClientError('x')))
    send.assert_not_called()
