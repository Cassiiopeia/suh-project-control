"""palworld_updater 단위 테스트 — subprocess/서비스는 전부 mock"""
import sys
import os
import time
import pytest
from unittest.mock import patch, MagicMock, call

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from service import palworld_updater as updater


APP_INFO_FIXTURE = '''
"2394010"
{
    "common" { "name" "Palworld Dedicated Server" }
    "depots"
    {
        "branches"
        {
            "public"
            {
                "buildid"   "20250701"
                "timeupdated"   "1751900000"
            }
            "beta" { "buildid" "99999999" }
        }
    }
}
'''


@pytest.fixture(autouse=True)
def reset_state():
    with updater._lock:
        updater._state.update({'status': 'idle', 'step': None, 'trigger': None,
                               'error': None, 'started_at': None, 'finished_at': None})
    updater._log.clear()
    updater._version.update({'local_build': None, 'remote_build': None,
                             'update_available': None, 'checked_at': None})
    yield


def test_parse_remote_buildid_public_branch():
    assert updater.parse_remote_buildid(APP_INFO_FIXTURE) == '20250701'


def test_parse_remote_buildid_missing_returns_none():
    assert updater.parse_remote_buildid('no vdf here') is None


def test_get_local_buildid_from_acf(tmp_path):
    acf = tmp_path / 'appmanifest_2394010.acf'
    acf.write_text('"AppState"\n{\n\t"appid"\t\t"2394010"\n\t"buildid"\t\t"20250601"\n}\n', encoding='utf-8')
    with patch.object(updater, 'APP_MANIFEST_PATH', str(acf)):
        assert updater.get_local_buildid() == '20250601'


def test_get_local_buildid_missing_file_returns_none():
    with patch.object(updater, 'APP_MANIFEST_PATH', r'C:\nonexistent\x.acf'):
        assert updater.get_local_buildid() is None


def test_check_for_update_detects_new_build():
    with patch.object(updater, 'get_local_buildid', return_value='100'), \
         patch.object(updater, 'get_remote_buildid', return_value='200'):
        info = updater.check_for_update()
    assert info['update_available'] is True
    assert info['local_build'] == '100' and info['remote_build'] == '200'


def test_check_for_update_same_build_not_available():
    with patch.object(updater, 'get_local_buildid', return_value='100'), \
         patch.object(updater, 'get_remote_buildid', return_value='100'):
        assert updater.check_for_update()['update_available'] is False


def test_check_for_update_unknown_when_remote_missing():
    with patch.object(updater, 'get_local_buildid', return_value='100'), \
         patch.object(updater, 'get_remote_buildid', return_value=None):
        assert updater.check_for_update()['update_available'] is None


def test_start_update_guards_double_run():
    with updater._lock:
        updater._state['status'] = 'running'
    assert updater.start_update('manual', '1.2.3.4') is False


def test_start_update_records_audit_and_spawns_thread():
    with patch.object(updater.audit_service, 'record') as mock_record, \
         patch.object(updater.threading, 'Thread') as mock_thread:
        assert updater.start_update('manual', '1.2.3.4') is True
    args = mock_record.call_args[0]
    assert args[1] == updater.AuditAction.SERVER_UPDATE
    assert args[2] == '1.2.3.4'
    assert mock_record.call_args[0][3]['trigger'] == 'manual'
    mock_thread.assert_called_once()
    assert updater._state['status'] == 'running'


def _mock_service(state='running'):
    service = MagicMock()
    service.get_service_state.return_value = state
    service.create_backup.return_value = {'name': 'backup_x'}
    return service


def test_run_update_happy_path_order():
    service = _mock_service()
    calls = []
    service.create_backup.side_effect = lambda: calls.append('backup') or {'name': 'b'}
    service.stop.side_effect = lambda: calls.append('stop')
    service.start.side_effect = lambda: calls.append('start')
    with patch.object(updater, 'PalworldService', create=True), \
         patch('service.palworld_service.PalworldService', return_value=service), \
         patch.object(updater, '_run_steamcmd_update', side_effect=lambda: calls.append('steamcmd')), \
         patch.object(updater, 'get_local_buildid', return_value='200'):
        updater._run_update()
    assert calls == ['backup', 'stop', 'steamcmd', 'start']
    assert updater._state['status'] == 'done'


def test_run_update_backup_failure_continues():
    service = _mock_service()
    service.create_backup.side_effect = RuntimeError('disk full')
    with patch('service.palworld_service.PalworldService', return_value=service), \
         patch.object(updater, '_run_steamcmd_update'), \
         patch.object(updater, 'get_local_buildid', return_value='200'):
        updater._run_update()
    assert updater._state['status'] == 'done'
    service.start.assert_called()


def test_run_update_steamcmd_failure_recovers_service():
    service = _mock_service()
    # steamcmd 실패 후 상태 확인 시 stopped → 재시작 시도
    service.get_service_state.side_effect = ['running', 'stopped']
    with patch('service.palworld_service.PalworldService', return_value=service), \
         patch.object(updater, '_run_steamcmd_update', side_effect=RuntimeError('steamcmd exit 8')):
        updater._run_update()
    assert updater._state['status'] == 'failed'
    assert 'steamcmd exit 8' in updater._state['error']
    service.start.assert_called()  # 복구 재시작


def test_get_state_includes_version_and_log():
    updater._log.append('line1')
    updater._version['local_build'] = '100'
    s = updater.get_state()
    assert s['status'] == 'idle' and s['local_build'] == '100' and s['log'] == ['line1']


def test_steamcmd_update_timeout_raises():
    fake_proc = MagicMock()
    fake_proc.stdout = iter([])          # 출력 없이 종료된 상황 재현
    fake_proc.wait.return_value = -9
    killed = {}
    fake_proc.kill.side_effect = lambda: killed.setdefault('yes', True)

    class FiringTimer:
        def __init__(self, interval, func):
            self.func = func
        def start(self):
            self.func()                  # 워치독이 즉시 발화한 상황
        def cancel(self):
            pass

    with patch.object(updater.subprocess, 'Popen', return_value=fake_proc), \
         patch.object(updater.threading, 'Timer', FiringTimer):
        with pytest.raises(RuntimeError, match='시간 초과'):
            updater._run_steamcmd_update()
    assert killed.get('yes') is True


def test_steamcmd_update_success_output_overrides_exit_code():
    fake_proc = MagicMock()
    fake_proc.stdout = iter(["Update state (0x61) downloading, progress: 50.0", "Success! App '2394010' fully installed."])
    fake_proc.wait.return_value = 7      # steamcmd는 성공해도 0이 아닐 수 있다
    with patch.object(updater.subprocess, 'Popen', return_value=fake_proc):
        updater._run_steamcmd_update()   # 예외 없어야 함
    assert any('Success!' in l for l in updater._log)
