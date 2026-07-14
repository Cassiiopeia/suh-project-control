"""test_palworld_metrics_history.py"""
import json
from service.palworld_metrics_history import (
    PalworldMetricsHistory, snapshot_from_metrics,
)

SAMPLE_METRICS = {
    'currentplayernum': 1, 'serverfps': 60, 'serverfpsaverage': 60.7,
    'serverframetime': 16.4, 'days': 35, 'basecampnum': 1,
    'uptime': 10116, 'maxplayernum': 32, 'ignored_extra': 'x',
}


def test_snapshot_extracts_known_keys_and_stamps_ts():
    point = snapshot_from_metrics(SAMPLE_METRICS, ts='2026-07-14T18:00:00')
    assert point['ts'] == '2026-07-14T18:00:00'
    assert point['serverfps'] == 60
    assert point['currentplayernum'] == 1
    assert 'ignored_extra' not in point


def test_add_and_history_roundtrip(tmp_path):
    h = PalworldMetricsHistory(path=str(tmp_path / 'm.jsonl'), maxlen=10)
    for i in range(5):
        h.add({'ts': f't{i}', 'serverfps': 60 - i})
    assert len(h.history()) == 5
    assert h.history(limit=2)[-1]['serverfps'] == 56
    assert h.history(limit=2)[0]['serverfps'] == 57


def test_ring_buffer_respects_maxlen(tmp_path):
    h = PalworldMetricsHistory(path=str(tmp_path / 'm.jsonl'), maxlen=3)
    for i in range(10):
        h.add({'ts': f't{i}', 'serverfps': i})
    hist = h.history()
    assert len(hist) == 3
    assert [p['serverfps'] for p in hist] == [7, 8, 9]


def test_persists_and_reloads_from_file(tmp_path):
    path = str(tmp_path / 'm.jsonl')
    h1 = PalworldMetricsHistory(path=path, maxlen=100)
    h1.add({'ts': 't0', 'serverfps': 60})
    h1.add({'ts': 't1', 'serverfps': 59})
    # 새 인스턴스가 파일에서 복구
    h2 = PalworldMetricsHistory(path=path, maxlen=100)
    assert len(h2.history()) == 2
    assert h2.history()[-1]['ts'] == 't1'


def test_reload_only_keeps_last_maxlen(tmp_path):
    path = str(tmp_path / 'm.jsonl')
    h1 = PalworldMetricsHistory(path=path, maxlen=100)
    for i in range(50):
        h1.add({'ts': f't{i}', 'serverfps': i})
    h2 = PalworldMetricsHistory(path=path, maxlen=10)
    assert len(h2.history()) == 10
    assert h2.history()[0]['serverfps'] == 40


def test_reload_skips_corrupt_lines(tmp_path):
    path = tmp_path / 'm.jsonl'
    path.write_text('{"ts":"t0","serverfps":60}\nNOT JSON\n{"ts":"t1","serverfps":59}\n', encoding='utf-8')
    h = PalworldMetricsHistory(path=str(path), maxlen=100)
    assert len(h.history()) == 2


def test_rotation_when_file_too_large(tmp_path):
    path = str(tmp_path / 'm.jsonl')
    h = PalworldMetricsHistory(path=path, maxlen=1000, max_bytes=200)
    for i in range(100):
        h.add({'ts': f't{i}', 'serverfps': i, 'pad': 'x' * 20})
    import os
    assert os.path.exists(path + '.1'), '회전 백업 파일이 있어야 한다'


def test_add_from_metrics_ignores_empty(tmp_path):
    h = PalworldMetricsHistory(path=str(tmp_path / 'm.jsonl'), maxlen=10)
    h.add_from_metrics(None)
    h.add_from_metrics({})
    assert h.history() == []
    h.add_from_metrics(SAMPLE_METRICS)
    assert len(h.history()) == 1
