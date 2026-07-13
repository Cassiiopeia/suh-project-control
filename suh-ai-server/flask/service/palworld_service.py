"""
Palworld server management service
NSSM 서비스 제어, 공식 REST API 중계, ini 관리, 로그, 백업
"""
import os
import shutil
import subprocess
import logging
from datetime import datetime

import requests

from config.palworld_config import (
    INI_PATH, SAVE_DIR, BACKUP_DIR, LOG_FILE,
    SERVICE_NAME, REST_BASE_URL, EDITABLE_KEYS,
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

    def start(self):
        self._service_command('Start')

    def stop(self):
        self._service_command('Stop')

    def restart(self):
        self._service_command('Restart')

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
        }
        if status['state'] != 'running':
            return status
        auth = self._rest_auth()
        try:
            info = requests.get(f'{REST_BASE_URL}/v1/api/info', auth=auth, timeout=3)
            players = requests.get(f'{REST_BASE_URL}/v1/api/players', auth=auth, timeout=3)
            metrics = requests.get(f'{REST_BASE_URL}/v1/api/metrics', auth=auth, timeout=3)
            status['info'] = info.json()
            status['players'] = players.json().get('players', [])
            status['metrics'] = metrics.json()
            status['rest_available'] = True
        except Exception as e:
            logger.warning(f'Palworld REST API unavailable: {e}')
        return status

    # --- 설정 ---

    def get_settings(self) -> dict:
        with open(INI_PATH, 'r', encoding='utf-8', errors='replace') as f:
            settings = parse_option_settings(f.read())
        return {'settings': settings, 'editable_keys': EDITABLE_KEYS}

    def update_settings(self, changes: dict) -> dict:
        if self.get_service_state() == 'running':
            raise ServerRunningError(
                'Server is running - stop the server before saving settings '
                '(changes would be overwritten on shutdown)'
            )
        filtered = {k: v for k, v in changes.items() if k in EDITABLE_KEYS}
        with open(INI_PATH, 'r', encoding='utf-8', errors='replace') as f:
            text = f.read()
        updated = update_option_settings(text, filtered)
        with open(INI_PATH, 'w', encoding='utf-8') as f:
            f.write(updated)
        logger.info(f'PalWorldSettings.ini updated: {list(filtered.keys())}')
        return {'settings': parse_option_settings(updated), 'editable_keys': EDITABLE_KEYS}

    # --- 로그 ---

    def tail_logs(self, lines: int = 200) -> list:
        lines = min(int(lines), 500)
        if not os.path.exists(LOG_FILE):
            return []
        with open(LOG_FILE, 'r', encoding='utf-8', errors='replace') as f:
            all_lines = f.readlines()
        return [l.rstrip('\n\r') for l in all_lines[-lines:]]

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
