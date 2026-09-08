"""
Sunshine(Moonlight 호스트) 제어 서비스
- 웹 API(47990, Basic 인증): 페어링 PIN 승인, 클라이언트 목록/해제, 세션 종료, 로그
- serverinfo(47989, 무인증): 스트림 상태(FREE/BUSY)와 실행 중 앱 ID
- Windows 서비스(SunshineService): PowerShell Start/Stop/Restart-Service
"""
import logging
import subprocess
import xml.etree.ElementTree as ET

import requests
import urllib3
from requests.auth import HTTPBasicAuth

from config.sunshine_config import (
    SUNSHINE_API_TIMEOUT_SECONDS, SUNSHINE_API_URL, SUNSHINE_KNOWN_APP_IDS, SUNSHINE_LOG_MAX_LINES,
    SUNSHINE_PUBLIC_HOST, SUNSHINE_SERVERINFO_URL, SUNSHINE_SERVICE_NAME,
    SUNSHINE_SERVICE_TIMEOUT_SECONDS, get_web_credentials,
)

logger = logging.getLogger(__name__)

# localhost 자체서명 인증서 경고가 매 호출마다 로그를 채우지 않도록 억제
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


class SunshineApiError(Exception):
    """Sunshine 웹 API 호출 실패. code 로 프론트가 원인(자격증명/인증/연결)을 구분한다."""

    def __init__(self, message, status_code=None, code='sunshine_api'):
        super().__init__(message)
        self.status_code = status_code
        self.code = code


class SunshineService:
    def __init__(self, api_url=SUNSHINE_API_URL, serverinfo_url=SUNSHINE_SERVERINFO_URL,
                 service_name=SUNSHINE_SERVICE_NAME, timeout=SUNSHINE_API_TIMEOUT_SECONDS):
        self.api_url = api_url.rstrip('/')
        self.serverinfo_url = serverinfo_url
        self.service_name = service_name
        self.timeout = timeout

    # ---------- 웹 API ----------
    def _auth(self):
        user, password = get_web_credentials()
        if not user or not password:
            raise SunshineApiError(
                'Sunshine 웹 자격증명이 설정되지 않았습니다 (.env 의 SUNSHINE_WEB_USER / SUNSHINE_WEB_PASSWORD)',
                code='credentials_missing')
        return HTTPBasicAuth(user, password)

    def _request(self, method, path, json_body=None, expect_json=True):
        auth = self._auth()
        try:
            resp = requests.request(method, self.api_url + path, json=json_body, auth=auth,
                                    verify=False, timeout=self.timeout)
        except requests.RequestException as e:
            raise SunshineApiError(f'Sunshine 웹 API 연결 실패: {e}', code='unreachable')

        if resp.status_code == 401:
            raise SunshineApiError('Sunshine 웹 API 인증 실패 (사용자명/비밀번호 확인)', 401, 'auth_failed')
        if resp.status_code >= 400:
            raise SunshineApiError(f'Sunshine 웹 API 오류 (HTTP {resp.status_code})', resp.status_code)
        if not expect_json:
            return resp.text
        try:
            data = resp.json()
        except ValueError:
            raise SunshineApiError('Sunshine 응답을 해석할 수 없습니다')
        # Sunshine은 실패도 200으로 주고 status:false 로 표시한다
        if isinstance(data, dict) and data.get('status') is False:
            raise SunshineApiError(data.get('error') or 'Sunshine 이 요청을 거부했습니다', resp.status_code)
        return data

    def list_clients(self) -> list:
        data = self._request('GET', '/api/clients/list')
        return [{'name': c.get('name', ''), 'uuid': c.get('uuid', '')}
                for c in data.get('named_certs', [])]

    def unpair_client(self, uuid: str) -> None:
        self._request('POST', '/api/clients/unpair', {'uuid': uuid})

    def submit_pin(self, pin: str, name: str) -> None:
        """Moonlight 가 띄운 PIN 을 승인해 페어링을 완료한다 (서버 화면의 PIN 입력창 대체)"""
        self._request('POST', '/api/pin', {'pin': pin, 'name': name})

    def close_session(self) -> None:
        """실행 중 앱을 종료해 BUSY 상태를 푼다 (연결된 클라이언트는 끊긴다)"""
        self._request('POST', '/api/apps/close', {})

    def read_logs(self, lines: int = 200) -> list:
        text = self._request('GET', '/api/logs', expect_json=False)
        lines = max(1, min(int(lines), SUNSHINE_LOG_MAX_LINES))
        return text.splitlines()[-lines:]

    # ---------- serverinfo ----------
    @staticmethod
    def parse_serverinfo(xml_text: str) -> dict:
        root = ET.fromstring(xml_text)

        def text(tag):
            node = root.find(tag)
            return (node.text or '').strip() if node is not None else ''

        raw_state = text('state')
        app_id = text('currentgame')
        return {
            'host_name': text('hostname'),
            'version': text('appversion'),
            # 예: SUNSHINE_SERVER_BUSY / SUNSHINE_SERVER_FREE
            'stream_state': 'BUSY' if 'BUSY' in raw_state else 'FREE',
            'current_app_id': app_id if app_id not in ('', '0') else None,
        }

    def fetch_serverinfo(self):
        """실패 시 None — Sunshine 이 내려가 있으면 정상 상황이므로 예외로 올리지 않는다"""
        try:
            resp = requests.get(self.serverinfo_url, timeout=self.timeout)
            resp.raise_for_status()
            return self.parse_serverinfo(resp.text)
        except (requests.RequestException, ET.ParseError) as e:
            logger.debug(f'Sunshine serverinfo unavailable: {e}')
            return None

    @staticmethod
    def resolve_app_name(app_id):
        if not app_id:
            return None
        return SUNSHINE_KNOWN_APP_IDS.get(str(app_id))

    # ---------- Windows 서비스 ----------
    def _powershell(self, command: str, timeout: int):
        return subprocess.run(['powershell', '-NoProfile', '-Command', command],
                              capture_output=True, text=True, timeout=timeout)

    def is_service_running(self) -> bool:
        try:
            res = self._powershell(f"(Get-Service -Name '{self.service_name}').Status", timeout=10)
            return res.returncode == 0 and res.stdout.strip().lower() == 'running'
        except (OSError, subprocess.SubprocessError) as e:
            logger.debug(f'Sunshine service status check failed: {e}')
            return False

    def _service_command(self, verb: str) -> bool:
        try:
            res = self._powershell(f"{verb}-Service -Name '{self.service_name}'",
                                   timeout=SUNSHINE_SERVICE_TIMEOUT_SECONDS)
            if res.returncode != 0:
                logger.error(f'{verb}-Service {self.service_name} failed: {res.stderr.strip()}')
                return False
            return True
        except (OSError, subprocess.SubprocessError) as e:
            logger.error(f'{verb}-Service {self.service_name} error: {e}')
            return False

    def start_service(self) -> bool:
        return self._service_command('Start')

    def stop_service(self) -> bool:
        return self._service_command('Stop')

    def restart_service(self) -> bool:
        # Restart-Service 는 의존 서비스까지 한 번에 처리하므로 stop→start 수동 조합보다 안전하다
        return self._service_command('Restart')

    # ---------- 종합 상태 ----------
    def get_status(self) -> dict:
        info = self.fetch_serverinfo()
        user, password = get_web_credentials()
        app_id = info['current_app_id'] if info else None
        return {
            'service_running': self.is_service_running(),
            'api_reachable': info is not None,
            'credentials_configured': bool(user and password),
            'stream_state': info['stream_state'] if info else 'UNKNOWN',
            'current_app_id': app_id,
            'current_app_name': self.resolve_app_name(app_id),
            'host_name': info['host_name'] if info else None,
            'version': info['version'] if info else None,
            'public_host': SUNSHINE_PUBLIC_HOST,
        }


sunshine_service = SunshineService()
