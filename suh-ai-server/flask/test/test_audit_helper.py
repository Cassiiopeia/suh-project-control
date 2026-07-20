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
