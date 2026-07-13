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
