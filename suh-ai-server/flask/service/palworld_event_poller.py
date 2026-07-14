"""
Palworld 접속/퇴장 이벤트 폴러
팰월드 데디 서버는 접속/퇴장을 어디에도 기록하지 않으므로
REST /v1/api/players를 주기 폴링해 diff로 이벤트를 자체 생성한다.
"""
import json
import logging
import os
import threading
from datetime import datetime

import requests

from config.palworld_config import LOG_SOURCES, REST_BASE_URL

logger = logging.getLogger(__name__)

EVENT_LOG_FILE = LOG_SOURCES['events']
MAX_EVENT_FILE_BYTES = 5 * 1024 * 1024
POLL_INTERVAL_SECONDS = 10


def _player_key(player: dict):
    # REST /players는 SteamID를 camelCase 'userId'로 준다. 과거 'userid'(소문자)로 읽어
    # 항상 None이 되어 name 폴백에 의존했다 → 닉네임 변경 시 오탐. userId 우선으로 정정.
    return player.get('userId') or player.get('userid') or player.get('name')


def diff_players(prev: list, curr: list) -> tuple:
    """이전/현재 접속자 스냅샷을 비교해 (joined, left)를 반환한다."""
    prev_keys = {_player_key(p) for p in prev}
    curr_keys = {_player_key(p) for p in curr}
    joined = [p for p in curr if _player_key(p) not in prev_keys]
    left = [p for p in prev if _player_key(p) not in curr_keys]
    return joined, left


class PalworldEventPoller:

    def __init__(self, service, interval: int = POLL_INTERVAL_SECONDS, metrics_history=None):
        self._service = service
        self._interval = interval
        self._prev_state = None
        self._prev_players = []
        self._stop = threading.Event()
        self._metrics_history = metrics_history

    def start(self) -> threading.Thread:
        thread = threading.Thread(target=self._run, daemon=True, name='palworld-event-poller')
        thread.start()
        return thread

    def _run(self):
        while not self._stop.is_set():
            try:
                self._tick()
            except Exception as e:
                # 틱 단위로 삼켜서 스레드 생존 보장
                logger.warning(f'Palworld event poller tick failed: {e}')
            self._stop.wait(self._interval)

    def _tick(self):
        state = self._service.get_service_state()
        if self._prev_state is not None and state != self._prev_state:
            if state == 'running':
                self._write_event({'type': 'server_up'})
            elif self._prev_state == 'running':
                self._write_event({'type': 'server_down'})
                self._prev_players = []
        self._prev_state = state
        if state != 'running':
            return
        # 메트릭 히스토리 적재 (그래프용). 이벤트 처리와 독립 — 실패해도 이벤트는 계속.
        self._record_metrics()
        players = self._fetch_players()
        if players is None:
            return  # REST 다운 — 스냅샷 유지, 다음 틱 재시도
        joined, left = diff_players(self._prev_players, players)
        for player in joined:
            self._write_event({'type': 'join', 'player': self._player_summary(player), 'count': len(players)})
        for player in left:
            self._write_event({'type': 'leave', 'player': self._player_summary(player), 'count': len(players)})
        self._prev_players = players

    def _record_metrics(self):
        if self._metrics_history is None:
            return
        try:
            resp = requests.get(f'{REST_BASE_URL}/v1/api/metrics',
                                auth=self._service._rest_auth(), timeout=3)
            resp.raise_for_status()
            self._metrics_history.add_from_metrics(resp.json())
        except Exception:
            pass  # 메트릭 한 틱 놓쳐도 무방 — 그래프에 구멍만 생긴다

    @staticmethod
    def _player_summary(player: dict) -> dict:
        return {
            'name': player.get('name'),
            'level': player.get('level'),
            'steamId': player.get('userId') or player.get('userid'),
        }

    def _fetch_players(self):
        try:
            resp = requests.get(f'{REST_BASE_URL}/v1/api/players',
                                auth=self._service._rest_auth(), timeout=3)
            resp.raise_for_status()
            return resp.json().get('players', [])
        except Exception:
            return None

    def _write_event(self, event: dict):
        event = dict(event)
        event['ts'] = datetime.now().isoformat(timespec='seconds')
        os.makedirs(os.path.dirname(EVENT_LOG_FILE), exist_ok=True)
        if os.path.exists(EVENT_LOG_FILE) and os.path.getsize(EVENT_LOG_FILE) > MAX_EVENT_FILE_BYTES:
            rotated = EVENT_LOG_FILE + '.1'
            if os.path.exists(rotated):
                os.remove(rotated)
            os.rename(EVENT_LOG_FILE, rotated)
        with open(EVENT_LOG_FILE, 'a', encoding='utf-8') as f:
            f.write(json.dumps(event, ensure_ascii=False) + '\n')
