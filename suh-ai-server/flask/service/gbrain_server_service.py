"""
gbrain HTTP 서버(MCP) 관리: 상태 종합, 로그, 서비스 제어, 관리자 로그인 경로 발급
- 상태 출처 3개: Windows 서비스(gbrain-http), /health(버전), config.json(DB·임베딩, 비번 제외)
- 로그인: 관리자 토큰 > POST /admin/api/issue-magic-link > 경로만 추출 (링크를 열거나 기록하지 않음)
"""
import json
import logging
import os
import re
from urllib.parse import urlsplit

import requests

from config.gbrain_server_config import (
    GBRAIN_ADMIN_GATE_VALID_SECONDS, GBRAIN_FORCED_STOP_AFTER_SECONDS, GBRAIN_HTTP_TIMEOUT_SECONDS, GBRAIN_LOG_MAX_LINES, GBRAIN_LOG_PATH,
    GBRAIN_LOG_TAIL_BYTES, GBRAIN_SERVER_URL, GBRAIN_SERVICE_NAME, GBRAIN_SERVICE_TIMEOUT_SECONDS,
    get_gbrain_config_path, read_admin_token,
)
from service.gbrain_admin_gate import create_gate_cookie_value, is_gate_cookie_valid
from util.windows_service_client import WindowsServiceClient

logger = logging.getLogger(__name__)

# gbrain 1회용 로그인 경로: /admin/auth/{nonce 64자 hex}
ADMIN_LOGIN_PATH_PATTERN = re.compile(r'^/admin/auth/[0-9a-f]{64}$')
MAGIC_LINK_ENDPOINT_PATH = '/admin/api/issue-magic-link'


class GbrainServerError(Exception):
    """gbrain 서버 관리 실패. code 로 화면이 원인을 구분, status_code 는 응답 상태"""

    def __init__(self, message, code, status_code=502):
        super().__init__(message)
        self.code = code
        self.status_code = status_code


class GbrainServerService:
    def __init__(self, server_url=GBRAIN_SERVER_URL, log_path=GBRAIN_LOG_PATH,
                 timeout_seconds=GBRAIN_HTTP_TIMEOUT_SECONDS):
        self.server_url = server_url.rstrip('/')
        self.log_path = log_path
        self.timeout_seconds = timeout_seconds
        self.windows_service = WindowsServiceClient(GBRAIN_SERVICE_NAME, GBRAIN_SERVICE_TIMEOUT_SECONDS,
                                                    forced_stop_after_seconds=GBRAIN_FORCED_STOP_AFTER_SECONDS)

    # ---------- 상태 ----------
    def fetch_health(self):
        """/health JSON (응답 없으면 None: 서비스 정지·기동 중은 정상 상황)"""
        try:
            response = requests.get(self.server_url + '/health', timeout=self.timeout_seconds)
            response.raise_for_status()
            return response.json()
        except (requests.RequestException, ValueError) as error:
            logger.debug(f'[gbrain server] health unavailable : {error}')
            return None

    @staticmethod
    def summarize_database_url(database_url):
        """DB 연결 문자열 > 호스트·포트·DB·계정 (비번은 담지 않음)"""
        if not database_url:
            return None
        parts = urlsplit(database_url)
        return {
            'host': parts.hostname,
            'port': parts.port,
            'name': parts.path.lstrip('/') or None,
            'user': parts.username,
        }

    def read_config_summary(self) -> dict:
        """config.json > 엔진·DB·임베딩 (못 읽으면 config_error 만)"""
        config_path = get_gbrain_config_path()
        try:
            with open(config_path, encoding='utf-8') as config_file:
                gbrain_config = json.load(config_file)
        except (OSError, ValueError):
            return {'config_error': 'config_unreadable'}
        return {
            'engine': gbrain_config.get('engine'),
            'database': self.summarize_database_url(gbrain_config.get('database_url')),
            'embedding_model': gbrain_config.get('embedding_model'),
            'embedding_dimensions': gbrain_config.get('embedding_dimensions'),
        }

    def get_status(self) -> dict:
        service_state = self.windows_service.get_state()
        health = self.fetch_health() or {}
        build = health.get('build') or {}
        return {
            'service_name': GBRAIN_SERVICE_NAME,
            'service_state': service_state,
            'service_running': service_state == 'running',
            'is_healthy': health.get('status') == 'ok',
            'version': health.get('version'),
            'installed_version': build.get('installed_version'),
            # 새 버전 설치 후 재시작 전이면 True
            'is_restart_pending': bool(build.get('restart_pending')),
            'server_url': self.server_url,
            'has_admin_token': read_admin_token() is not None,
            **self.read_config_summary(),
        }

    # ---------- 로그 ----------
    def read_logs(self, lines: int) -> list:
        """로그 파일 끝 N줄 (최대 GBRAIN_LOG_MAX_LINES, 끝 1MB 만 읽음)"""
        line_count = max(1, min(int(lines), GBRAIN_LOG_MAX_LINES))
        try:
            with open(self.log_path, 'rb') as log_file:
                log_file.seek(0, os.SEEK_END)
                file_size = log_file.tell()
                log_file.seek(max(0, file_size - GBRAIN_LOG_TAIL_BYTES))
                tail_text = log_file.read().decode('utf-8', errors='replace')
        except OSError:
            raise GbrainServerError('gbrain 로그 파일을 읽을 수 없습니다', 'log_unreadable', 404)
        return tail_text.splitlines()[-line_count:]

    # ---------- 서비스 제어 ----------
    def start_service(self) -> bool:
        return self.windows_service.start()

    def stop_service(self) -> bool:
        return self.windows_service.stop()

    def restart_service(self) -> bool:
        return self.windows_service.restart()

    # ---------- 관리자 로그인 ----------
    def create_admin_login(self) -> dict:
        """1회용 로그인 경로 + 게이트 쿠키 값 (링크를 GET 하지 않음, 경로·쿠키를 기록하지 않음)"""
        admin_token = read_admin_token()
        if admin_token is None:
            raise GbrainServerError('gbrain 관리자 토큰 파일이 없습니다 (scripts/setup-gbrain-http.ps1 실행 필요)',
                                    'admin_token_missing', 503)
        login_path = self._issue_login_path(admin_token)
        return {
            'login_path': login_path,
            'gate_cookie_value': create_gate_cookie_value(admin_token, GBRAIN_ADMIN_GATE_VALID_SECONDS),
            'gate_valid_seconds': GBRAIN_ADMIN_GATE_VALID_SECONDS,
        }

    def _issue_login_path(self, admin_token: str) -> str:
        try:
            response = requests.post(self.server_url + MAGIC_LINK_ENDPOINT_PATH, json={},
                                     headers={'Authorization': f'Bearer {admin_token}'},
                                     timeout=self.timeout_seconds)
        except requests.RequestException as error:
            logger.warning(f'[gbrain admin login] rejected 502 : server unreachable {type(error).__name__}')
            raise GbrainServerError('gbrain 서버에 연결할 수 없습니다', 'unreachable')
        if response.status_code == 401:
            logger.warning('[gbrain admin login] rejected 502 : admin token not accepted by gbrain')
            raise GbrainServerError('gbrain 이 관리자 토큰을 거부했습니다 (서비스 재시작 필요할 수 있음)',
                                    'admin_token_rejected')
        if response.status_code >= 400:
            logger.warning(f'[gbrain admin login] rejected 502 : gbrain status {response.status_code}')
            raise GbrainServerError(f'gbrain 로그인 링크 발급 실패 (HTTP {response.status_code})', 'gbrain_error')
        try:
            login_path = urlsplit(str(response.json().get('url', ''))).path
        except (ValueError, AttributeError):
            login_path = ''
        if not ADMIN_LOGIN_PATH_PATTERN.match(login_path):
            logger.warning('[gbrain admin login] rejected 502 : unexpected login link shape')
            raise GbrainServerError('gbrain 로그인 링크 형식이 예상과 다릅니다', 'invalid_login_link')
        return login_path

    @staticmethod
    def is_admin_gate_valid(cookie_value) -> bool:
        return is_gate_cookie_valid(read_admin_token(), cookie_value)


gbrain_server_service = GbrainServerService()
