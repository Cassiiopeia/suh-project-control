"""test_palworld_event_poller.py"""
import json
import pytest
from unittest.mock import patch, MagicMock

import service.palworld_event_poller as poller_module
from service.palworld_event_poller import PalworldEventPoller, diff_players


# --- diff_players (순수 함수) ---

def test_diff_players_detects_join():
    joined, left = diff_players([], [{'userid': 'a', 'name': 'A'}])
    assert [p['name'] for p in joined] == ['A']
    assert left == []


def test_diff_players_detects_leave():
    joined, left = diff_players([{'userid': 'a', 'name': 'A'}], [])
    assert joined == []
    assert [p['name'] for p in left] == ['A']


def test_diff_players_no_change():
    players = [{'userid': 'a', 'name': 'A'}, {'userid': 'b', 'name': 'B'}]
    joined, left = diff_players(players, list(players))
    assert joined == [] and left == []


def test_diff_players_falls_back_to_name_key():
    joined, left = diff_players([{'name': 'A'}], [{'name': 'A'}, {'name': 'B'}])
    assert [p['name'] for p in joined] == ['B']
    assert left == []


# --- 이벤트 기록 ---

@pytest.fixture
def event_file(tmp_path, monkeypatch):
    path = tmp_path / 'logs' / 'palworld-events.jsonl'
    monkeypatch.setattr(poller_module, 'EVENT_LOG_FILE', str(path))
    return path


def _read_events(event_file):
    return [json.loads(l) for l in event_file.read_text(encoding='utf-8').strip().splitlines()]


def test_write_event_creates_dir_and_appends(event_file):
    poller = PalworldEventPoller(MagicMock())
    poller._write_event({'type': 'server_up'})
    events = _read_events(event_file)
    assert events[0]['type'] == 'server_up'
    assert 'ts' in events[0]


def test_write_event_rotates_when_too_big(event_file, monkeypatch):
    monkeypatch.setattr(poller_module, 'MAX_EVENT_FILE_BYTES', 10)
    event_file.parent.mkdir(parents=True, exist_ok=True)
    event_file.write_text('x' * 100, encoding='utf-8')
    poller = PalworldEventPoller(MagicMock())
    poller._write_event({'type': 'server_up'})
    assert (event_file.parent / 'palworld-events.jsonl.1').exists()
    assert len(_read_events(event_file)) == 1


# --- tick 로직 ---

def test_tick_records_join_and_leave(event_file):
    service = MagicMock()
    service.get_service_state.return_value = 'running'
    poller = PalworldEventPoller(service)
    poller._prev_state = 'running'
    with patch.object(poller, '_fetch_players', return_value=[{'userid': 'a', 'name': 'A', 'level': 12}]):
        poller._tick()
    with patch.object(poller, '_fetch_players', return_value=[]):
        poller._tick()
    events = _read_events(event_file)
    assert [e['type'] for e in events] == ['join', 'leave']
    assert events[0]['player']['name'] == 'A'
    assert events[0]['count'] == 1


def test_tick_records_server_transitions(event_file):
    service = MagicMock()
    poller = PalworldEventPoller(service)
    service.get_service_state.return_value = 'stopped'
    poller._tick()  # 첫 tick은 기준 상태만 기억 (이벤트 없음)
    service.get_service_state.return_value = 'running'
    with patch.object(poller, '_fetch_players', return_value=[]):
        poller._tick()
    service.get_service_state.return_value = 'stopped'
    poller._tick()
    assert [e['type'] for e in _read_events(event_file)] == ['server_up', 'server_down']


def test_tick_skips_players_when_rest_down(event_file):
    service = MagicMock()
    service.get_service_state.return_value = 'running'
    poller = PalworldEventPoller(service)
    poller._prev_state = 'running'
    poller._prev_players = [{'userid': 'a', 'name': 'A'}]
    with patch.object(poller, '_fetch_players', return_value=None):
        poller._tick()
    assert not event_file.exists()          # REST 다운 → 이벤트 기록 없음
    assert poller._prev_players == [{'userid': 'a', 'name': 'A'}]  # 스냅샷 유지
