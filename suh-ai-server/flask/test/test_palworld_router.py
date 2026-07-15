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
    # ServerRunningError 분기는 방어적으로 유지 — 더 이상 서비스가 던지지 않지만
    # 만약 발생하면 여전히 409로 처리되어야 한다.
    with patch('router.palworld_router.palworld_service.update_settings',
               side_effect=ServerRunningError('running')):
        resp = client.put('/palworld/settings', json={'ServerName': 'X'})
    assert resp.status_code == 409


def test_put_settings_while_running_saves_pending_returns_200(client):
    before = {'settings': {'ServerName': '"Old"'}, 'editable_keys': [], 'pending': {}}
    after = {'settings': {'ServerName': '"Old"'}, 'pending': {'ServerName': 'New'}, 'applied': False}
    with patch('router.palworld_router.palworld_service.get_settings', return_value=before), \
         patch('router.palworld_router.palworld_service.update_settings', return_value=after), \
         patch('router.palworld_router.audit_service.record') as mock_record:
        resp = client.put('/palworld/settings', json={'ServerName': 'New'})
    assert resp.status_code == 200
    data = resp.get_json()
    assert data['applied'] is False
    assert data['pending'] == {'ServerName': 'New'}
    detail = mock_record.call_args[0][3]
    assert detail['applied'] is False
    assert detail['changed'] == {'ServerName': {'from': '"Old"', 'to': 'New'}}


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
    after = {'settings': {'ServerName': '"Old"', 'ExpRate': '3.0'}, 'editable_keys': [], 'applied': True}
    with patch('router.palworld_router.palworld_service.get_settings', return_value=before), \
         patch('router.palworld_router.palworld_service.update_settings', return_value=after), \
         patch('router.palworld_router.audit_service.record') as mock_record:
        resp = client.put('/palworld/settings', json={'ExpRate': '3.0', 'ServerName': 'Old'})
    assert resp.status_code == 200
    detail = mock_record.call_args[0][3]
    assert detail == {'changed': {'ExpRate': {'from': '2.0', 'to': '3.0'}}, 'applied': True}


def test_put_settings_no_change_skips_audit(client):
    same = {'settings': {'ExpRate': '2.0'}, 'editable_keys': [], 'applied': True}
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


def test_put_settings_masks_sensitive_values(client):
    before = {'settings': {'ServerPassword': '"1234"'}, 'editable_keys': []}
    after = {'settings': {'ServerPassword': '"5678"'}, 'editable_keys': [], 'applied': True}
    with patch('router.palworld_router.palworld_service.get_settings', return_value=before), \
         patch('router.palworld_router.palworld_service.update_settings', return_value=after), \
         patch('router.palworld_router.audit_service.record') as mock_record:
        resp = client.put('/palworld/settings', json={'ServerPassword': '5678'})
    assert resp.status_code == 200
    detail = mock_record.call_args[0][3]
    assert detail == {'changed': {'ServerPassword': {'from': '***', 'to': '***'}}, 'applied': True}


def test_put_settings_while_running_masks_sensitive_pending(client):
    before = {'settings': {'ServerPassword': '"1234"'}, 'editable_keys': [], 'pending': {}}
    after = {'settings': {'ServerPassword': '"1234"'}, 'pending': {'ServerPassword': '5678'}, 'applied': False}
    with patch('router.palworld_router.palworld_service.get_settings', return_value=before), \
         patch('router.palworld_router.palworld_service.update_settings', return_value=after), \
         patch('router.palworld_router.audit_service.record') as mock_record:
        resp = client.put('/palworld/settings', json={'ServerPassword': '5678'})
    assert resp.status_code == 200
    detail = mock_record.call_args[0][3]
    assert detail == {'changed': {'ServerPassword': {'from': '***', 'to': '***'}}, 'applied': False}


def test_control_unmapped_action_skips_audit_and_succeeds(client):
    with patch('router.palworld_router.palworld_service.start'), \
         patch('router.palworld_router.audit_service.record') as mock_record, \
         patch.dict('router.palworld_router._CONTROL_AUDIT_ACTIONS', {}, clear=True):
        resp = client.post('/palworld/start')
    assert resp.status_code == 200
    assert resp.get_json()['success'] is True
    mock_record.assert_not_called()


# --- 서버 바이너리 업데이트 ---

def test_update_starts_and_returns_202(client):
    with patch('router.palworld_router.palworld_updater.start_update', return_value=True) as mock_start:
        resp = client.post('/palworld/update')
    assert resp.status_code == 202
    assert mock_start.call_args[0][0] == 'manual'


def test_update_conflict_when_already_running(client):
    with patch('router.palworld_router.palworld_updater.start_update', return_value=False):
        resp = client.post('/palworld/update')
    assert resp.status_code == 409


def test_update_status_returns_state(client):
    fake = {'status': 'running', 'step': 'download', 'log': ['x'], 'update_available': True}
    with patch('router.palworld_router.palworld_updater.get_state', return_value=fake):
        resp = client.get('/palworld/update/status')
    assert resp.status_code == 200
    assert resp.get_json()['step'] == 'download'


def test_update_check_returns_version_info(client):
    fake = {'local_build': '1', 'remote_build': '2', 'update_available': True}
    with patch('router.palworld_router.palworld_updater.check_for_update', return_value=fake):
        resp = client.post('/palworld/update/check')
    assert resp.status_code == 200
    assert resp.get_json()['update_available'] is True
