"""
Palworld server management service
NSSM 서비스 제어, 공식 REST API 중계, ini 관리, 로그, 백업
"""
import os
import json
import shutil
import subprocess
import time
import logging
from datetime import datetime

import requests

from config.palworld_config import (
    INI_PATH, SAVE_DIR, BACKUP_DIR, LOG_SOURCES,
    SERVICE_NAME, REST_BASE_URL, EDITABLE_KEYS,
    PUBLIC_HOST, PUBLIC_PORT,
    PALSERVER_ARGS, REQUIRED_ARG_FLAG, NSSM_PATH,
    PENDING_SETTINGS_PATH,
)
from service.palworld_ini import parse_option_settings, update_option_settings

logger = logging.getLogger(__name__)


class ServerRunningError(Exception):
    """서버 가동 중에는 ini를 수정할 수 없다 (종료 시 덮어씌워져 유실됨)"""


class PalworldService:

    # --- 서비스 제어 ---

    def get_service_state(self) -> str:
        result = subprocess.run(
            ['sc', 'query', SERVICE_NAME],
            capture_output=True, text=True, timeout=10
        )
        if result.returncode != 0:
            return 'not_installed'
        if 'RUNNING' in result.stdout:
            return 'running'
        return 'stopped'

    def _service_command(self, verb: str):
        result = subprocess.run(
            ['powershell', '-NoProfile', '-Command', f'{verb}-Service -Name {SERVICE_NAME} -ErrorAction Stop'],
            capture_output=True, text=True, timeout=120
        )
        if result.returncode != 0:
            raise RuntimeError(f'{verb}-Service failed: {result.stderr.strip()}')

    # --- NSSM 실행 인자 자가 치유 ---

    @staticmethod
    def _needs_log_flag(current_args: str) -> bool:
        """현재 NSSM AppParameters 문자열에 -log 플래그가 빠졌는지 (공백 경계로 판정)."""
        tokens = (current_args or '').split()
        return REQUIRED_ARG_FLAG not in tokens

    def _get_nssm_parameters(self) -> str:
        result = subprocess.run(
            [NSSM_PATH, 'get', SERVICE_NAME, 'AppParameters'],
            capture_output=True, text=True, timeout=15
        )
        if result.returncode != 0:
            raise RuntimeError(f'nssm get AppParameters failed: {result.stderr.strip()}')
        # nssm은 UTF-16LE로 출력하는 경우가 있어 text=True로도 NUL이 섞일 수 있다 → 정리
        return result.stdout.replace('\x00', '').strip()

    def ensure_log_enabled(self) -> bool:
        """서버 시작/재시작 전에 NSSM 실행 인자에 -log가 있는지 보장한다.

        Flask는 LocalSystem 권한으로 돌기 때문에 nssm set이 가능하다.
        이미 -log가 있으면 아무것도 하지 않고 False, 새로 넣었으면 True를 반환한다.
        치유에 실패해도 서버 제어 자체를 막지 않도록 예외는 삼키고 경고만 남긴다.
        """
        try:
            current = self._get_nssm_parameters()
            if not self._needs_log_flag(current):
                return False
            result = subprocess.run(
                [NSSM_PATH, 'set', SERVICE_NAME, 'AppParameters', PALSERVER_ARGS],
                capture_output=True, text=True, timeout=15
            )
            if result.returncode != 0:
                logger.warning(f'nssm set AppParameters failed (권한 부족 가능): {result.stderr.strip()}')
                return False
            logger.info(f'NSSM AppParameters 자가 치유: -log 추가됨 → {PALSERVER_ARGS}')
            return True
        except Exception as e:
            logger.warning(f'ensure_log_enabled 실패: {e}')
            return False

    def start(self):
        self.ensure_log_enabled()
        self._service_command('Start')

    def stop(self):
        self._service_command('Stop')
        self._apply_pending_settings()

    def restart(self):
        healed = self.ensure_log_enabled()
        if self._load_pending():
            # 대기 중인 설정 변경이 있으면 stop()이 중지 완료 직후 pending을 적용하므로
            # Restart-Service(내부적으로도 stop→start지만 우리 쪽 훅을 안 탐) 대신
            # stop()+start()로 대체해 pending 적용 경로를 반드시 거치게 한다.
            self.stop()
            self.start()
        else:
            # -log를 새로 넣었다면 반드시 프로세스를 완전히 재기동해야 인자가 적용된다.
            # Restart-Service는 stop→start라 새 AppParameters로 뜬다.
            self._service_command('Restart')
        return {'log_flag_added': healed}

    # --- pending 설정 (실행 중 저장분 임시 보관) ---

    def _load_pending(self) -> dict:
        if not os.path.exists(PENDING_SETTINGS_PATH):
            return {}
        try:
            with open(PENDING_SETTINGS_PATH, 'r', encoding='utf-8') as f:
                data = json.load(f)
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError) as e:
            logger.warning(f'pending settings 읽기 실패: {e}')
            return {}

    def _save_pending(self, data: dict):
        try:
            os.makedirs(os.path.dirname(PENDING_SETTINGS_PATH), exist_ok=True)
            with open(PENDING_SETTINGS_PATH, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False)
        except OSError as e:
            logger.warning(f'pending settings 저장 실패: {e}')

    def _clear_pending(self):
        try:
            if os.path.exists(PENDING_SETTINGS_PATH):
                os.remove(PENDING_SETTINGS_PATH)
        except OSError as e:
            logger.warning(f'pending settings 삭제 실패: {e}')

    def _apply_pending_settings(self, wait: bool = True):
        """대기 중인 설정 변경을 ini에 반영한다. 서비스가 이미 중지된 상태에서 호출된다는
        전제 — PalServer는 종료 시 메모리 값으로 ini를 덮어쓰므로, 그 덮어쓰기가 끝난
        뒤에 적용해야 유실되지 않는다. 종료 시 ini 플러시가 늦게 끝날 수 있어 기본적으로
        잠깐 대기한다(서버가 이미 정지 중이던 경로에서는 대기가 필요 없어 생략 가능).
        예외는 삼키고 경고만 남겨 중지 흐름을 막지 않는다.
        """
        pending = self._load_pending()
        if not pending:
            return
        try:
            if wait:
                time.sleep(2)
            with open(INI_PATH, 'r', encoding='utf-8', errors='replace') as f:
                text = f.read()
            updated = update_option_settings(text, pending)
            with open(INI_PATH, 'w', encoding='utf-8') as f:
                f.write(updated)
            self._clear_pending()
            logger.info(f'대기 중이던 설정 변경을 ini에 적용: {list(pending.keys())}')
        except Exception as e:
            logger.warning(f'pending settings 적용 실패 (다음 중지 시 재시도): {e}')

    # --- 상태 (공식 REST API 중계) ---

    def _rest_auth(self):
        admin_password = ''
        try:
            with open(INI_PATH, 'r', encoding='utf-8', errors='replace') as f:
                settings = parse_option_settings(f.read())
            admin_password = settings.get('AdminPassword', '""').strip('"')
        except (OSError, ValueError):
            pass
        return ('admin', admin_password)

    def get_status(self) -> dict:
        status = {
            'state': self.get_service_state(),
            'rest_available': False,
            'info': None,
            'players': [],
            'metrics': None,
            'settings': None,
        }
        if status['state'] != 'running':
            return status
        auth = self._rest_auth()
        # info/players/metrics/settings를 독립적으로 조회한다. 한 엔드포인트가 실패해도
        # 성공한 나머지 데이터는 버리지 않는다. 하나라도 응답하면 rest_available=True.
        endpoints = {
            'info': f'{REST_BASE_URL}/v1/api/info',
            'players': f'{REST_BASE_URL}/v1/api/players',
            'metrics': f'{REST_BASE_URL}/v1/api/metrics',
            'settings': f'{REST_BASE_URL}/v1/api/settings',
        }
        for name, url in endpoints.items():
            try:
                resp = requests.get(url, auth=auth, timeout=3)
                resp.raise_for_status()
                data = resp.json()
                status[name] = data.get('players', []) if name == 'players' else data
                status['rest_available'] = True
            except Exception as e:
                logger.warning(f'Palworld REST API {name} unavailable: {e}')
        return status

    # --- 설정 ---

    def get_settings(self) -> dict:
        with open(INI_PATH, 'r', encoding='utf-8', errors='replace') as f:
            settings = parse_option_settings(f.read())
        return {'settings': settings, 'editable_keys': EDITABLE_KEYS, 'pending': self._load_pending()}

    def update_settings(self, changes: dict) -> dict:
        filtered = {k: v for k, v in changes.items() if k in EDITABLE_KEYS}
        if self.get_service_state() == 'running':
            # 실행 중에는 ini에 직접 쓰지 않는다 — PalServer가 종료 시 메모리 값으로
            # 덮어써 유실되기 때문. 대신 pending에 병합 저장하고 재시작/중지 시 적용한다.
            merged = {**self._load_pending(), **filtered}
            self._save_pending(merged)
            logger.info(f'서버 실행 중 — 설정 변경을 pending에 저장: {list(filtered.keys())}')
            with open(INI_PATH, 'r', encoding='utf-8', errors='replace') as f:
                current_settings = parse_option_settings(f.read())
            return {'settings': current_settings, 'editable_keys': EDITABLE_KEYS,
                     'pending': merged, 'applied': False}

        # 정지 중: 기존에 쌓인 pending이 있으면 먼저 적용한 뒤(서버가 안 돌고 있으므로
        # 종료 시 ini 플러시 대기가 필요 없다) 요청받은 값을 이어서 저장한다.
        self._apply_pending_settings(wait=False)
        with open(INI_PATH, 'r', encoding='utf-8', errors='replace') as f:
            text = f.read()
        updated = update_option_settings(text, filtered)
        with open(INI_PATH, 'w', encoding='utf-8') as f:
            f.write(updated)
        logger.info(f'PalWorldSettings.ini updated: {list(filtered.keys())}')
        return {'settings': parse_option_settings(updated), 'editable_keys': EDITABLE_KEYS,
                 'pending': {}, 'applied': True}

    # --- 접속 가이드 ---

    @staticmethod
    def _unquote(value) -> str:
        value = str(value)
        return value[1:-1] if value.startswith('"') and value.endswith('"') else value

    def get_guide_info(self) -> dict:
        """게임 접속 가이드용 정보. ini를 못 읽어도 공개 주소는 항상 내려준다."""
        info = {
            'address': f'{PUBLIC_HOST}:{PUBLIC_PORT}',
            'server_name': None,
            'password': None,
            'max_players': None,
            'has_password': False,
        }
        try:
            with open(INI_PATH, 'r', encoding='utf-8', errors='replace') as f:
                settings = parse_option_settings(f.read())
        except (OSError, ValueError) as e:
            logger.warning(f'guide: ini unavailable: {e}')
            return info
        info['server_name'] = self._unquote(settings.get('ServerName', '""')) or None
        password = self._unquote(settings.get('ServerPassword', '""'))
        info['password'] = password or None
        info['has_password'] = bool(password)
        info['max_players'] = settings.get('ServerPlayerMaxNum')
        return info

    # --- 로그 ---

    TAIL_READ_BYTES = 256 * 1024        # 일반 tail: 파일 끝에서 이만큼만 읽는다
    # 잡음 숨김 tail: 실제 이벤트가 REST 잡음에 파묻혀 있어 훨씬 넓게 훑어야 한다.
    NOISE_TAIL_READ_BYTES = 8 * 1024 * 1024
    # 우리 폴러가 REST API를 주기 호출하며 남기는 잡음 (게임 로그의 99% 이상 차지)
    NOISE_MARKER = 'REST accessed endpoint'

    def tail_logs(self, source: str = 'game', lines: int = 200, hide_noise: bool = False) -> dict:
        if source not in LOG_SOURCES:
            raise ValueError(f'Unknown log source: {source}')
        lines = min(int(lines), 500)
        path = LOG_SOURCES[source]
        result = {'source': source, 'log_file': path, 'exists': False, 'size_bytes': 0, 'logs': []}
        if not os.path.exists(path):
            return result
        size = os.path.getsize(path)
        result['exists'] = True
        result['size_bytes'] = size
        read_bytes = self.NOISE_TAIL_READ_BYTES if hide_noise else self.TAIL_READ_BYTES
        with open(path, 'rb') as f:
            f.seek(max(0, size - read_bytes))
            data = f.read()
        all_lines = data.decode('utf-8', errors='replace').splitlines()
        if size > read_bytes and all_lines:
            all_lines = all_lines[1:]  # seek 지점의 첫 줄은 중간에서 잘렸을 수 있다
        if hide_noise:
            # REST 폴링 잡음 + 빈 줄(stdout이 줄마다 공백행을 끼워 넣음)을 함께 제거해
            # 실제 이벤트만 남긴다.
            all_lines = [ln for ln in all_lines
                         if ln.strip() and self.NOISE_MARKER not in ln]
        result['logs'] = all_lines[-lines:]
        return result

    # --- 백업 ---

    def list_backups(self) -> list:
        if not os.path.isdir(BACKUP_DIR):
            return []
        backups = []
        for name in sorted(os.listdir(BACKUP_DIR), reverse=True):
            path = os.path.join(BACKUP_DIR, name)
            if not os.path.isdir(path):
                continue
            size = sum(
                os.path.getsize(os.path.join(root, f))
                for root, _, files in os.walk(path) for f in files
            )
            backups.append({
                'name': name,
                'size_mb': round(size / 1024 / 1024, 1),
                'created': datetime.fromtimestamp(os.path.getctime(path)).isoformat(),
            })
        return backups

    def create_backup(self) -> dict:
        if not os.path.isdir(SAVE_DIR):
            raise FileNotFoundError(f'SaveGames directory not found: {SAVE_DIR}')
        name = datetime.now().strftime('%Y%m%d_%H%M%S')
        dest = os.path.join(BACKUP_DIR, name)
        shutil.copytree(SAVE_DIR, dest)
        logger.info(f'Backup created: {dest}')
        return {'name': name}
