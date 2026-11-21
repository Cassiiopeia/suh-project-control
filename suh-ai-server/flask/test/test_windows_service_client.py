"""WindowsServiceClient: 상태 문자열 변환, 미설치·실행 실패 구분, 제어 동사 (PowerShell 은 모킹)"""
import subprocess

from util import windows_service_client as module
from util.windows_service_client import STATE_NOT_INSTALLED, STATE_UNKNOWN, WindowsServiceClient


def _fake_run(monkeypatch, returncode=0, stdout='', calls=None):
    def fake_run(command, **kwargs):
        if calls is not None:
            calls.append(command)
        return subprocess.CompletedProcess(command, returncode, stdout=stdout, stderr='denied')
    monkeypatch.setattr(module.subprocess, 'run', fake_run)


def test_상태는_소문자_밑줄로_바꾼다(monkeypatch):
    _fake_run(monkeypatch, stdout='StartPending\n')
    assert WindowsServiceClient('gbrain-http').get_state() == 'start_pending'


def test_구동_중이면_is_running_참(monkeypatch):
    calls = []
    _fake_run(monkeypatch, stdout='Running\n', calls=calls)
    assert WindowsServiceClient('gbrain-http').is_running() is True
    assert "Get-Service -Name 'gbrain-http'" in calls[0][-1]


def test_서비스를_못_찾으면_미설치(monkeypatch):
    _fake_run(monkeypatch, returncode=1)
    assert WindowsServiceClient('gbrain-http').get_state() == STATE_NOT_INSTALLED


def test_PowerShell_실행_실패면_확인_불가(monkeypatch):
    def boom(*args, **kwargs):
        raise FileNotFoundError('powershell')
    monkeypatch.setattr(module.subprocess, 'run', boom)
    assert WindowsServiceClient('gbrain-http').get_state() == STATE_UNKNOWN


def test_재시작은_Restart_동사를_쓴다(monkeypatch):
    calls = []
    _fake_run(monkeypatch, calls=calls)
    assert WindowsServiceClient('gbrain-http').restart() is True
    assert "Restart-Service -Name 'gbrain-http' -ErrorAction Stop" in calls[0][-1]


def test_제어_실패면_False(monkeypatch):
    _fake_run(monkeypatch, returncode=1)
    assert WindowsServiceClient('gbrain-http').stop() is False


def test_강제_정지_옵션은_대기_후_래퍼를_종료하는_스크립트를_쓴다(monkeypatch):
    calls = []
    _fake_run(monkeypatch, stdout='forced\n', calls=calls)
    client = WindowsServiceClient('gbrain-http', forced_stop_after_seconds=8)

    assert client.stop() is True
    script = calls[0][-1]
    assert "$name='gbrain-http'" in script and 'AddSeconds(8)' in script
    assert 'Stop-Process -Id $wrapperProcessId -Force' in script


def test_강제_정지_옵션의_재시작은_정지_후_시작(monkeypatch):
    calls = []
    _fake_run(monkeypatch, calls=calls)
    client = WindowsServiceClient('gbrain-http', forced_stop_after_seconds=8)

    assert client.restart() is True
    assert 'Stop-Service -Name $name -NoWait' in calls[0][-1]
    assert "Start-Service -Name 'gbrain-http'" in calls[1][-1]


def test_강제_정지가_실패하면_시작하지_않는다(monkeypatch):
    calls = []
    _fake_run(monkeypatch, returncode=1, calls=calls)
    assert WindowsServiceClient('gbrain-http', forced_stop_after_seconds=8).restart() is False
    assert len(calls) == 1
