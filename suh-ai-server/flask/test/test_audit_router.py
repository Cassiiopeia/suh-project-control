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


def test_audit_logs_success_false_filter(client):
    with patch('router.audit_router.audit_service.query_logs', return_value=FAKE) as mock_q:
        client.get('/audit/logs?success=false')
    assert mock_q.call_args.kwargs['success'] is False


def test_audit_logs_rejects_bad_numbers(client):
    resp = client.get('/audit/logs?limit=abc')
    assert resp.status_code == 400
