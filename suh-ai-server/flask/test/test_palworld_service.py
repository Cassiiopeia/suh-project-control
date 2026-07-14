"""test_palworld_service.py"""
import pytest
from unittest.mock import patch, MagicMock
from service.palworld_service import PalworldService, ServerRunningError

SAMPLE_INI = '''[/Script/Pal.PalGameWorldSettings]
OptionSettings=(ServerName="Test",AdminPassword="secret",ServerPlayerMaxNum=32,CrossplayPlatforms=(Steam,Xbox,PS5,Mac),RESTAPIEnabled=True)
'''


@pytest.fixture
def service():
    return PalworldService()


def _sc_result(stdout, returncode=0):
    mock = MagicMock()
    mock.stdout = stdout
    mock.returncode = returncode
    return mock


def test_get_service_state_running(service):
    with patch('service.palworld_service.subprocess.run',
               return_value=_sc_result("SERVICE_NAME: PalServer\n        STATE : 4  RUNNING\n")):
        assert service.get_service_state() == 'running'


def test_get_service_state_stopped(service):
    with patch('service.palworld_service.subprocess.run',
               return_value=_sc_result("SERVICE_NAME: PalServer\n        STATE : 1  STOPPED\n")):
        assert service.get_service_state() == 'stopped'


def test_get_service_state_not_installed(service):
    with patch('service.palworld_service.subprocess.run',
               return_value=_sc_result("", returncode=1060)):
        assert service.get_service_state() == 'not_installed'


def test_update_settings_blocked_while_running(service):
    with patch.object(service, 'get_service_state', return_value='running'):
        with pytest.raises(ServerRunningError):
            service.update_settings({"ServerName": "New"})


def test_update_settings_writes_when_stopped(service, tmp_path):
    ini = tmp_path / "PalWorldSettings.ini"
    ini.write_text(SAMPLE_INI, encoding='utf-8')
    with patch.object(service, 'get_service_state', return_value='stopped'), \
         patch('service.palworld_service.INI_PATH', str(ini)):
        result = service.update_settings({"ServerName": "New"})
    assert result["settings"]["ServerName"] == '"New"'
    assert 'ServerName="New"' in ini.read_text(encoding='utf-8')


def test_update_settings_can_switch_to_steam_only_without_corrupting_ini(service, tmp_path):
    ini = tmp_path / "PalWorldSettings.ini"
    ini.write_text(SAMPLE_INI, encoding='utf-8')
    with patch.object(service, 'get_service_state', return_value='stopped'), \
         patch('service.palworld_service.INI_PATH', str(ini)):
        result = service.update_settings({"CrossplayPlatforms": "(Steam)"})
    assert result["settings"]["CrossplayPlatforms"] == "(Steam)"
    assert result["settings"]["RESTAPIEnabled"] == "True"


def test_update_settings_ignores_non_editable_keys(service, tmp_path):
    ini = tmp_path / "PalWorldSettings.ini"
    ini.write_text(SAMPLE_INI, encoding='utf-8')
    with patch.object(service, 'get_service_state', return_value='stopped'), \
         patch('service.palworld_service.INI_PATH', str(ini)):
        service.update_settings({"AdminPassword": "hacked", "ServerName": "OK"})
    text = ini.read_text(encoding='utf-8')
    assert 'AdminPassword="secret"' in text


def test_get_status_degrades_when_rest_down(service):
    with patch.object(service, 'get_service_state', return_value='running'), \
         patch('service.palworld_service.requests.get', side_effect=Exception("conn refused")):
        status = service.get_status()
    assert status['state'] == 'running'
    assert status['rest_available'] is False


def test_start_calls_powershell(service):
    with patch('service.palworld_service.subprocess.run', return_value=_sc_result("", 0)) as mock_run:
        service.start()
    args = mock_run.call_args[0][0]
    assert 'Start-Service' in ' '.join(args)


# --- tail_logs (source 선택 + seek tail) ---

def test_tail_logs_unknown_source_raises(service):
    with pytest.raises(ValueError):
        service.tail_logs('nope', 100)


def test_tail_logs_missing_file_reports_path(service, tmp_path):
    missing = str(tmp_path / 'Pal.log')
    with patch.dict('service.palworld_service.LOG_SOURCES', {'game': missing}):
        result = service.tail_logs('game', 100)
    assert result['exists'] is False
    assert result['log_file'] == missing
    assert result['logs'] == []
    assert result['source'] == 'game'


def test_tail_logs_returns_last_lines(service, tmp_path):
    log = tmp_path / 'Pal.log'
    log.write_text('\n'.join(f'line{i}' for i in range(300)) + '\n', encoding='utf-8')
    with patch.dict('service.palworld_service.LOG_SOURCES', {'game': str(log)}):
        result = service.tail_logs('game', 100)
    assert result['exists'] is True
    assert len(result['logs']) == 100
    assert result['logs'][-1] == 'line299'
    assert result['size_bytes'] == log.stat().st_size


def test_tail_logs_reads_only_tail_of_large_file(service, tmp_path):
    # 60000줄 x 11바이트 ≈ 660KB > TAIL_READ_BYTES(256KB) — seek 경로 검증
    log = tmp_path / 'Pal.log'
    log.write_text('\n'.join(f'row{i:07d}' for i in range(60000)) + '\n', encoding='utf-8')
    with patch.dict('service.palworld_service.LOG_SOURCES', {'game': str(log)}):
        result = service.tail_logs('game', 50)
    assert len(result['logs']) == 50
    assert result['logs'][-1] == 'row0059999'
    assert result['logs'][0] == 'row0059950'


# --- 접속 가이드 ---

GUIDE_INI = '''[/Script/Pal.PalGameWorldSettings]
OptionSettings=(ServerName="팰 사냥터",ServerPassword="1234",AdminPassword="secret",ServerPlayerMaxNum=32)
'''


def test_get_guide_info_reads_ini(service, tmp_path):
    ini = tmp_path / 'PalWorldSettings.ini'
    ini.write_text(GUIDE_INI, encoding='utf-8')
    with patch('service.palworld_service.INI_PATH', str(ini)):
        info = service.get_guide_info()
    assert info == {
        'address': 'suh-project.synology.me:8211',
        'server_name': '팰 사냥터',
        'password': '1234',
        'max_players': '32',
        'has_password': True,
    }


def test_get_guide_info_without_password_is_public(service, tmp_path):
    ini = tmp_path / 'PalWorldSettings.ini'
    ini.write_text(GUIDE_INI.replace('ServerPassword="1234"', 'ServerPassword=""'), encoding='utf-8')
    with patch('service.palworld_service.INI_PATH', str(ini)):
        info = service.get_guide_info()
    assert info['password'] is None
    assert info['has_password'] is False


def test_get_guide_info_without_ini_returns_address_only(service, tmp_path):
    with patch('service.palworld_service.INI_PATH', str(tmp_path / 'none.ini')):
        info = service.get_guide_info()
    assert info['address'] == 'suh-project.synology.me:8211'
    assert info['server_name'] is None
    assert info['has_password'] is False
