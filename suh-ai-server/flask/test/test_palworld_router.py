"""test_palworld_router.py"""
import pytest
from unittest.mock import patch
from flask import Flask
from service.palworld_service import ServerRunningError


@pytest.fixture
def client():
    from router.palworld_router import palworld_bp
    app = Flask(__name__)
    app.register_blueprint(palworld_bp)
    return app.test_client()


def test_status_returns_service_result(client):
    fake = {'state': 'running', 'rest_available': True, 'info': {}, 'players': [], 'metrics': {}}
    with patch('router.palworld_router.palworld_service.get_status', return_value=fake):
        resp = client.get('/palworld/status')
    assert resp.status_code == 200
    assert resp.get_json()['state'] == 'running'


def test_start_success(client):
    with patch('router.palworld_router.palworld_service.start'):
        resp = client.post('/palworld/start')
    assert resp.status_code == 200
    assert resp.get_json()['success'] is True


def test_start_failure_returns_500(client):
    with patch('router.palworld_router.palworld_service.start', side_effect=RuntimeError('boom')):
        resp = client.post('/palworld/start')
    assert resp.status_code == 500


def test_put_settings_while_running_returns_409(client):
    with patch('router.palworld_router.palworld_service.update_settings',
               side_effect=ServerRunningError('running')):
        resp = client.put('/palworld/settings', json={'ServerName': 'X'})
    assert resp.status_code == 409


def test_put_settings_requires_json(client):
    resp = client.put('/palworld/settings', data='not json', content_type='text/plain')
    assert resp.status_code == 400


def test_create_backup(client):
    with patch('router.palworld_router.palworld_service.create_backup', return_value={'name': '20260713_120000'}):
        resp = client.post('/palworld/backups')
    assert resp.status_code == 200
    assert resp.get_json()['name'] == '20260713_120000'
