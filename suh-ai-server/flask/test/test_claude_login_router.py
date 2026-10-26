"""test_claude_login_router.py — 코드 요청·상태·캡처 API + 감사 기록"""
from unittest.mock import patch

import pytest
from flask import Flask

from service.audit_service import AuditAction

RUNNING_STATE = {'job_id': 'job1', 'status': 'running', 'code': None, 'mail_received_at': None}
ISSUED_STATE = {'job_id': 'job1', 'status': 'issued', 'code': '027696',
                'mail_received_at': '2026-10-26T00:34:20+00:00'}


@pytest.fixture
def client():
    from router.claude_login_router import claude_login_bp
    app = Flask(__name__)
    app.register_blueprint(claude_login_bp)
    return app.test_client()


def recorded_actions(record):
    return [call.args[1] for call in record.call_args_list]


def test_request_returns_state(client):
    with patch('router.claude_login_router.code_service.start_request', return_value=(RUNNING_STATE, True)), \
            patch('util.audit_helper.audit_service.record'):
        resp = client.post('/claude-login/code/request', json={'trigger': 'auto'})
    assert resp.status_code == 200
    assert resp.get_json()['job_id'] == 'job1'


def test_request_not_configured_returns_400(client):
    from service.claude_login_code_service import NotConfiguredError
    with patch('router.claude_login_router.code_service.start_request', side_effect=NotConfiguredError()), \
            patch('util.audit_helper.audit_service.record') as record:
        resp = client.post('/claude-login/code/request', json={'trigger': 'auto'})
    assert resp.status_code == 400
    assert resp.get_json()['error'] == 'not_configured'
    assert record.call_count == 0


def test_request_records_audit_only_for_new_job(client):
    with patch('router.claude_login_router.code_service.start_request', return_value=(RUNNING_STATE, True)), \
            patch('util.audit_helper.audit_service.record') as record:
        client.post('/claude-login/code/request', json={'trigger': 'manual'})
    assert recorded_actions(record) == [AuditAction.CLAUDE_CODE_REQUEST]
    assert record.call_args.args[3]['trigger'] == 'manual'

    with patch('router.claude_login_router.code_service.start_request', return_value=(RUNNING_STATE, False)), \
            patch('util.audit_helper.audit_service.record') as record:
        client.post('/claude-login/code/request', json={'trigger': 'auto'})
    assert record.call_count == 0


def test_request_unknown_trigger_falls_back_to_manual(client):
    with patch('router.claude_login_router.code_service.start_request', return_value=(RUNNING_STATE, True)) as start, \
            patch('util.audit_helper.audit_service.record'):
        client.post('/claude-login/code/request', json={'trigger': '<script>'})
    assert start.call_args.args[0] == 'manual'


def test_status_records_view_once_when_code_present(client):
    with patch('router.claude_login_router.code_service.get_state', return_value=ISSUED_STATE), \
            patch('router.claude_login_router.audit_service.record') as record:
        first = client.get('/claude-login/code/status', headers={'X-Forwarded-For': '9.9.9.9'})
        client.get('/claude-login/code/status', headers={'X-Forwarded-For': '9.9.9.9'})
    assert first.get_json()['code'] == '027696'
    assert recorded_actions(record) == [AuditAction.CLAUDE_CODE_VIEW]
    assert record.call_args.kwargs['client_ip'] == '9.9.9.9'
    assert '027696' not in repr(record.call_args)


def test_status_without_code_records_no_view(client):
    with patch('router.claude_login_router.code_service.get_state', return_value=RUNNING_STATE), \
            patch('router.claude_login_router.audit_service.record') as record:
        resp = client.get('/claude-login/code/status')
    assert resp.status_code == 200
    assert record.call_count == 0


def test_screenshot_404_when_missing(client, tmp_path):
    with patch('router.claude_login_router.code_service.SCREENSHOT_PATH', str(tmp_path / 'none.png')):
        resp = client.get('/claude-login/code/screenshot')
    assert resp.status_code == 404


def test_request_response_never_contains_code(client):
    # 코드는 열람 감사가 붙는 status 로만 전달
    with patch('router.claude_login_router.code_service.start_request', return_value=(ISSUED_STATE, False)), \
            patch('util.audit_helper.audit_service.record'):
        resp = client.post('/claude-login/code/request', json={'trigger': 'auto'})
    assert resp.get_json()['code'] is None
    assert resp.get_json()['status'] == 'issued'
