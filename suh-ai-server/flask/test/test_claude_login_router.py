"""test_claude_login_router.py — 계정 관리·코드 요청·상태·캡처 API + 감사 기록"""
from unittest.mock import patch

import pytest
from flask import Flask

from service import claude_login_account_service as account_service
from service.audit_service import AuditAction
from service.claude_login_account_repository import AccountStoreUnavailableError, DuplicateAccountError

RUNNING_STATE = {'account_id': 1, 'job_id': 'job1', 'status': 'running', 'code': None, 'mail_received_at': None}
ISSUED_STATE = {'account_id': 1, 'job_id': 'job1', 'status': 'issued', 'code': '027696',
                'mail_received_at': '2026-10-26T00:34:20+00:00'}
ACCOUNT_RESPONSE = {'id': 1, 'display_name': '회사', 'gmail_address': 'work@gmail.com', 'is_enabled': True,
                    'is_last_test_failed': False, 'last_success_at': None, 'created_at': None}
SERVICE = 'router.claude_login_router.account_service'
CODE_SERVICE = 'router.claude_login_router.code_service'


@pytest.fixture
def client():
    from router.claude_login_router import claude_login_bp
    app = Flask(__name__)
    app.register_blueprint(claude_login_bp)
    return app.test_client()


def recorded_actions(record):
    return [call.args[1] for call in record.call_args_list]


# 계정 관리 API

def test_create_account_returns_201_and_audits_without_password(client):
    with patch(f'{SERVICE}.create_account', return_value=ACCOUNT_RESPONSE) as create, \
            patch('util.audit_helper.audit_service.record') as record:
        resp = client.post('/claude-login/accounts', json={
            'display_name': '회사', 'gmail_address': 'work@gmail.com', 'app_password': 'abcdefghijklmnop'})
    assert resp.status_code == 201
    assert create.call_args.args == ('회사', 'work@gmail.com', 'abcdefghijklmnop')
    assert recorded_actions(record) == [AuditAction.CLAUDE_ACCOUNT_CREATE]
    assert 'abcdefghijklmnop' not in repr(record.call_args)


@pytest.mark.parametrize('error, status, code', [
    (account_service.AccountLoginFailedError('imap login failed'), 400, 'imap_login_failed'),
    (account_service.SecretNotConfiguredError(), 400, 'secret_not_configured'),
    (DuplicateAccountError('x'), 409, 'duplicate_account'),
    (AccountStoreUnavailableError('down'), 503, 'store_unavailable'),
    (account_service.AccountValidationError('invalid_app_password'), 400, 'invalid_app_password'),
])
def test_create_account_errors_map_to_json_and_audit_failure(client, error, status, code):
    with patch(f'{SERVICE}.create_account', side_effect=error), \
            patch('util.audit_helper.audit_service.record') as record:
        resp = client.post('/claude-login/accounts', json={'app_password': 'abcdefghijklmnop'})
    assert resp.status_code == status
    assert resp.get_json()['error'] == code
    assert record.call_args.kwargs['success'] is False
    assert 'abcdefghijklmnop' not in repr(record.call_args)


def test_update_account_audits_changed_fields_only_names(client):
    with patch(f'{SERVICE}.update_account', return_value=ACCOUNT_RESPONSE) as update, \
            patch('util.audit_helper.audit_service.record') as record:
        resp = client.put('/claude-login/accounts/1', json={'is_enabled': False, 'app_password': 'abcdefghijklmnop'})
    assert resp.status_code == 200
    assert update.call_args.kwargs == {'display_name': None, 'is_enabled': False, 'app_password': 'abcdefghijklmnop'}
    detail = record.call_args.args[3]
    assert detail['changed_fields'] == ['app_password', 'is_enabled']
    assert 'abcdefghijklmnop' not in repr(record.call_args)


def test_delete_missing_account_returns_404(client):
    with patch(f'{SERVICE}.delete_account', side_effect=account_service.AccountNotFoundError(9)), \
            patch('util.audit_helper.audit_service.record'):
        resp = client.delete('/claude-login/accounts/9')
    assert resp.status_code == 404
    assert resp.get_json()['error'] == 'account_not_found'


def test_test_account_returns_result(client):
    with patch(f'{SERVICE}.verify_saved_account', return_value={'account': ACCOUNT_RESPONSE, 'is_success': False}), \
            patch('util.audit_helper.audit_service.record') as record:
        resp = client.post('/claude-login/accounts/1/test')
    assert resp.get_json()['is_success'] is False
    assert recorded_actions(record) == [AuditAction.CLAUDE_ACCOUNT_TEST]


def test_list_accounts(client):
    with patch(f'{SERVICE}.list_accounts', return_value=[ACCOUNT_RESPONSE]):
        resp = client.get('/claude-login/accounts')
    assert resp.get_json()['accounts'] == [ACCOUNT_RESPONSE]


# 코드 대기 API

def test_request_passes_account_id_and_hides_code(client):
    with patch(f'{CODE_SERVICE}.start_requests', return_value=[(ISSUED_STATE, False)]) as start, \
            patch('util.audit_helper.audit_service.record') as record:
        resp = client.post('/claude-login/code/request', json={'trigger': 'manual', 'account_id': 1})
    assert start.call_args.args[2] == 1
    assert resp.get_json()['accounts'][0]['code'] is None
    assert record.call_count == 0


def test_request_records_audit_only_for_new_jobs(client):
    with patch(f'{CODE_SERVICE}.start_requests', return_value=[(RUNNING_STATE, True)]), \
            patch('util.audit_helper.audit_service.record') as record:
        client.post('/claude-login/code/request', json={'trigger': 'auto'})
    assert recorded_actions(record) == [AuditAction.CLAUDE_CODE_REQUEST]
    assert record.call_args.args[3]['jobs'] == [{'account_id': 1, 'job_id': 'job1'}]


def test_request_secret_missing_returns_400(client):
    with patch(f'{CODE_SERVICE}.start_requests', side_effect=account_service.SecretNotConfiguredError()), \
            patch('util.audit_helper.audit_service.record') as record:
        resp = client.post('/claude-login/code/request', json={'trigger': 'auto'})
    assert resp.status_code == 400
    assert resp.get_json()['error'] == 'secret_not_configured'
    assert record.call_count == 0


def test_request_unknown_trigger_falls_back_to_manual(client):
    with patch(f'{CODE_SERVICE}.start_requests', return_value=[]) as start, \
            patch('util.audit_helper.audit_service.record'):
        client.post('/claude-login/code/request', json={'trigger': '<script>'})
    assert start.call_args.args[0] == 'manual'


def test_request_rejects_non_int_account_id(client):
    resp = client.post('/claude-login/code/request', json={'account_id': '1'})
    assert resp.status_code == 400


def test_status_records_view_once_per_account_job(client):
    with patch(f'{CODE_SERVICE}.get_states', return_value=[ISSUED_STATE, RUNNING_STATE | {'account_id': 2}]), \
            patch('router.claude_login_router.audit_service.record') as record:
        first = client.get('/claude-login/code/status', headers={'X-Forwarded-For': '9.9.9.9'})
        client.get('/claude-login/code/status', headers={'X-Forwarded-For': '9.9.9.9'})
    assert first.get_json()['accounts'][0]['code'] == '027696'
    assert recorded_actions(record) == [AuditAction.CLAUDE_CODE_VIEW]
    assert record.call_args.args[3]['account_id'] == 1
    assert '027696' not in repr(record.call_args)


def test_status_sends_view_project_event_once_without_code(client):
    state = ISSUED_STATE | {'display_name': '회사'}
    with patch(f'{CODE_SERVICE}.get_states', return_value=[state]), \
            patch('router.claude_login_router.audit_service.record'), \
            patch('router.claude_login_router.send_project_event') as send:
        client.get('/claude-login/code/status', headers={'X-Forwarded-For': '8.8.8.8', 'User-Agent': 'UA'})
        client.get('/claude-login/code/status', headers={'X-Forwarded-For': '8.8.8.8', 'User-Agent': 'UA'})
    assert send.call_count == 1
    assert send.call_args.args[:3] == ('suh-ai', 'claude-code', 'Claude 코드 열람')
    assert dict(send.call_args.kwargs['fields'])['계정'] == '회사'
    assert send.call_args.kwargs['dedupe_key'] == 'claude-code:view:job1:8.8.8.8'
    assert '027696' not in repr(send.call_args)
    assert 'gmail.com' not in repr(send.call_args)


def test_screenshot_requires_account_id_and_404_when_missing(client, tmp_path):
    assert client.get('/claude-login/code/screenshot').status_code == 400
    with patch(f'{CODE_SERVICE}.SCREENSHOT_DIRECTORY', str(tmp_path)):
        resp = client.get('/claude-login/code/screenshot?account_id=1')
    assert resp.status_code == 404
