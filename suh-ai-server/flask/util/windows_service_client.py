"""
Windows 서비스 제어 공통: 상태 조회, 시작·중지·재시작 (PowerShell *-Service)
Flask 는 LocalSystem 으로 돌아 서비스 제어 권한이 있음
정지 강제 종료 옵션: 정지가 제한 시간 안에 안 끝나면 서비스 래퍼(NSSM) 프로세스만 종료 > Stopped 확인
"""
import logging
import subprocess

logger = logging.getLogger(__name__)

# 상태 조회 제한 시간 (초)
STATUS_TIMEOUT_SECONDS = 10
# Get-Service 가 서비스를 못 찾았을 때 돌려주는 상태
STATE_NOT_INSTALLED = 'not_installed'
# PowerShell 실행 자체가 실패했을 때 상태
STATE_UNKNOWN = 'unknown'


# 정지 강제 종료 스크립트: 정지 요청 > 대기 > 아직 안 멈추면 래퍼 프로세스 종료 > Stopped 대기
# NSSM 2.24 + bun: 앱은 이미 종료됐는데 StopPending 에 멈추는 경우가 있어 사용 (gbrain-http, #201)
FORCED_STOP_SCRIPT = (
    "$name='{service_name}'; "
    "Stop-Service -Name $name -NoWait -ErrorAction SilentlyContinue; "
    "$deadline=(Get-Date).AddSeconds({graceful_seconds}); "
    "while((Get-Service $name).Status -ne 'Stopped' -and (Get-Date) -lt $deadline){{Start-Sleep -Milliseconds 500}}; "
    "if((Get-Service $name).Status -ne 'Stopped'){{"
    "$wrapperProcessId=(Get-CimInstance Win32_Service -Filter \"Name='$name'\").ProcessId; "
    "if($wrapperProcessId -gt 0){{Stop-Process -Id $wrapperProcessId -Force}}; "
    "Write-Output 'forced'; "
    "$deadline=(Get-Date).AddSeconds(10); "
    "while((Get-Service $name).Status -ne 'Stopped' -and (Get-Date) -lt $deadline){{Start-Sleep -Milliseconds 500}}}}; "
    "if((Get-Service $name).Status -ne 'Stopped'){{exit 1}}"
)


class WindowsServiceClient:
    def __init__(self, service_name: str, command_timeout_seconds: int = 30,
                 forced_stop_after_seconds: int | None = None):
        self.service_name = service_name
        self.command_timeout_seconds = command_timeout_seconds
        # None: 일반 Stop/Restart-Service, 숫자: 그 초 안에 안 멈추면 래퍼 강제 종료
        self.forced_stop_after_seconds = forced_stop_after_seconds

    def _run_powershell(self, command: str, timeout_seconds: int):
        return subprocess.run(['powershell', '-NoProfile', '-Command', command],
                              capture_output=True, text=True, timeout=timeout_seconds)

    def get_state(self) -> str:
        """서비스 상태 소문자 (running, stopped, start_pending 등) / not_installed / unknown"""
        try:
            result = self._run_powershell(
                f"(Get-Service -Name '{self.service_name}' -ErrorAction Stop).Status", STATUS_TIMEOUT_SECONDS)
        except (OSError, subprocess.SubprocessError) as error:
            logger.debug(f'[windows service] status check failed : {self.service_name} {error}')
            return STATE_UNKNOWN
        if result.returncode != 0:
            return STATE_NOT_INSTALLED
        # StartPending > start_pending
        raw_state = result.stdout.strip()
        return ''.join('_' + char.lower() if char.isupper() and index else char.lower()
                       for index, char in enumerate(raw_state)) or STATE_UNKNOWN

    def is_running(self) -> bool:
        return self.get_state() == 'running'

    def _run_service_verb(self, verb: str) -> bool:
        try:
            result = self._run_powershell(f"{verb}-Service -Name '{self.service_name}' -ErrorAction Stop",
                                          self.command_timeout_seconds)
        except (OSError, subprocess.SubprocessError) as error:
            logger.error(f'[windows service] {verb} error : {self.service_name} {error}')
            return False
        if result.returncode != 0:
            logger.error(f'[windows service] {verb} failed : {self.service_name} {result.stderr.strip()}')
            return False
        return True

    def start(self) -> bool:
        return self._run_service_verb('Start')

    def _stop_with_forced_fallback(self) -> bool:
        script = FORCED_STOP_SCRIPT.format(service_name=self.service_name,
                                           graceful_seconds=self.forced_stop_after_seconds)
        try:
            result = self._run_powershell(script, self.command_timeout_seconds)
        except (OSError, subprocess.SubprocessError) as error:
            logger.error(f'[windows service] forced stop error : {self.service_name} {error}')
            return False
        if 'forced' in result.stdout:
            logger.warning(f'[windows service] stop forced : {self.service_name} wrapper killed after '
                           f'{self.forced_stop_after_seconds}s')
        if result.returncode != 0:
            logger.error(f'[windows service] forced stop failed : {self.service_name} {result.stderr.strip()}')
            return False
        return True

    def stop(self) -> bool:
        if self.forced_stop_after_seconds is not None:
            return self._stop_with_forced_fallback()
        return self._run_service_verb('Stop')

    def restart(self) -> bool:
        if self.forced_stop_after_seconds is not None:
            # 강제 종료 옵션: 정지(필요 시 래퍼 종료) > 시작
            return self._stop_with_forced_fallback() and self.start()
        # 의존 서비스까지 한 번에 처리 > stop·start 수동 조합보다 안전
        return self._run_service_verb('Restart')
