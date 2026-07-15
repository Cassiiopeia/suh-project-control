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


def test_logs_invalid_lines_returns_400(client):
    resp = client.get('/palworld/logs?lines=abc')
    assert resp.status_code == 400


def test_logs_invalid_source_returns_400(client):
    with patch('router.palworld_router.palworld_service.tail_logs',
               side_effect=ValueError('Unknown log source: nope')):
        resp = client.get('/palworld/logs?source=nope')
    assert resp.status_code == 400


def test_logs_passes_source_and_lines(client):
    fake = {'source': 'events', 'log_file': 'x.jsonl', 'exists': True, 'size_bytes': 10, 'logs': ['a']}
    with patch('router.palworld_router.palworld_service.tail_logs', return_value=fake) as mock_tail:
        resp = client.get('/palworld/logs?source=events&lines=100')
    assert resp.status_code == 200
    assert resp.get_json()['logs'] == ['a']
    mock_tail.assert_called_once_with('events', 100, False)


def test_logs_defaults_to_game_source(client):
    fake = {'source': 'game', 'log_file': 'Pal.log', 'exists': True, 'size_bytes': 10, 'logs': []}
    with patch('router.palworld_router.palworld_service.tail_logs', return_value=fake) as mock_tail:
        resp = client.get('/palworld/logs')
    assert resp.status_code == 200
    mock_tail.assert_called_once_with('game', 200, False)


def test_logs_passes_hide_noise_flag(client):
    fake = {'source': 'game', 'log_file': 'x', 'exists': True, 'size_bytes': 1, 'logs': []}
    with patch('router.palworld_router.palworld_service.tail_logs', return_value=fake) as mock_tail:
        client.get('/palworld/logs?source=game&lines=200&hide_noise=true')
    mock_tail.assert_called_once_with('game', 200, True)


def test_guide_returns_info(client):
    fake = {'address': 'suh-project.synology.me:8211', 'server_name': '팰 사냥터',
            'password': '1234', 'max_players': '32', 'has_password': True}
    with patch('router.palworld_router.palworld_service.get_guide_info', return_value=fake):
        resp = client.get('/palworld/guide')
    assert resp.status_code == 200
    assert resp.get_json()['address'] == 'suh-project.synology.me:8211'


# --- 감사로그 연동 ---

def test_control_success_records_audit(client):
    with patch('router.palworld_router.palworld_service.start'), \
         patch('router.palworld_router.audit_service.record') as mock_record:
        resp = client.post('/palworld/start', headers={'X-Forwarded-For': '9.9.9.9, 10.0.0.1'})
    assert resp.status_code == 200
    args = mock_record.call_args[0]
    assert args[1].value == 'SERVER_START'
    assert args[2] == '9.9.9.9'  # XFF 첫 값


def test_control_failure_does_not_record_audit(client):
    with patch('router.palworld_router.palworld_service.start', side_effect=RuntimeError('boom')), \
         patch('router.palworld_router.audit_service.record') as mock_record:
        resp = client.post('/palworld/start')
    assert resp.status_code == 500
    mock_record.assert_not_called()


def test_put_settings_records_changed_diff_only(client):
    before = {'settings': {'ServerName': '"Old"', 'ExpRate': '2.0'}, 'editable_keys': []}
    after = {'settings': {'ServerName': '"Old"', 'ExpRate': '3.0'}, 'editable_keys': []}
    with patch('router.palworld_router.palworld_service.get_settings', return_value=before), \
         patch('router.palworld_router.palworld_service.update_settings', return_value=after), \
         patch('router.palworld_router.audit_service.record') as mock_record:
        resp = client.put('/palworld/settings', json={'ExpRate': '3.0', 'ServerName': 'Old'})
    assert resp.status_code == 200
    detail = mock_record.call_args[0][3]
    assert detail == {'changed': {'ExpRate': {'from': '2.0', 'to': '3.0'}}}


def test_put_settings_no_change_skips_audit(client):
    same = {'settings': {'ExpRate': '2.0'}, 'editable_keys': []}
    with patch('router.palworld_router.palworld_service.get_settings', return_value=same), \
         patch('router.palworld_router.palworld_service.update_settings', return_value=same), \
         patch('router.palworld_router.audit_service.record') as mock_record:
        resp = client.put('/palworld/settings', json={'ExpRate': '2.0'})
    assert resp.status_code == 200
    mock_record.assert_not_called()


def test_create_backup_records_audit(client):
    with patch('router.palworld_router.palworld_service.create_backup', return_value={'name': '20260714_1'}), \
         patch('router.palworld_router.audit_service.record') as mock_record:
        resp = client.post('/palworld/backups')
    assert resp.status_code == 200
    assert mock_record.call_args[0][1].value == 'BACKUP_CREATE'
    assert mock_record.call_args[0][3] == {'name': '20260714_1'}


def test_logs_source_audit_uses_audit_service(client):
    fake = {'source': 'audit', 'log_file': 'postgresql://h:5430/db', 'exists': True, 'size_bytes': 0, 'logs': ['x']}
    with patch('router.palworld_router.audit_service.list_logs', return_value=fake) as mock_list, \
         patch('router.palworld_router.palworld_service.tail_logs') as mock_tail:
        resp = client.get('/palworld/logs?source=audit&lines=100')
    assert resp.status_code == 200
    assert resp.get_json()['logs'] == ['x']
    mock_list.assert_called_once_with(100)
    mock_tail.assert_not_called()
