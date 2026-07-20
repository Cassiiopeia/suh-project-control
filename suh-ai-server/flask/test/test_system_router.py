"""test_system_router.py — /system/metrics 응답 형태·limit 클램프·빈 버퍼 폴백"""
import pytest
from flask import Flask

import router.system_router as sr


class FakeHistory:
    def __init__(self, points):
        self._points = points

    def history(self, limit=None):
        points = list(self._points)
        if limit is not None and limit > 0:
            points = points[-limit:]
        return points


@pytest.fixture
def client():
    app = Flask(__name__)
    app.register_blueprint(sr.system_bp)
    return app.test_client()


def test_metrics_returns_current_and_history(client, monkeypatch):
    points = [{'ts': f't{i}', 'cpu': float(i)} for i in range(5)]
    monkeypatch.setattr(sr, 'system_metrics_history', FakeHistory(points))
    data = client.get('/system/metrics?limit=3').get_json()
    assert data['current']['ts'] == 't4'
    assert [p['ts'] for p in data['history']] == ['t2', 't3', 't4']


def test_metrics_limit_zero_skips_history(client, monkeypatch):
    points = [{'ts': 't0', 'cpu': 1.0}]
    monkeypatch.setattr(sr, 'system_metrics_history', FakeHistory(points))
    data = client.get('/system/metrics?limit=0').get_json()
    assert data['history'] == []
    assert data['current']['ts'] == 't0'


def test_metrics_invalid_limit_falls_back_to_default(client, monkeypatch):
    points = [{'ts': f't{i}'} for i in range(200)]
    monkeypatch.setattr(sr, 'system_metrics_history', FakeHistory(points))
    data = client.get('/system/metrics?limit=abc').get_json()
    assert len(data['history']) == 120


def test_metrics_limit_clamped_to_maxlen(client, monkeypatch):
    monkeypatch.setattr(sr, 'system_metrics_history', FakeHistory([{'ts': 't0'}]))
    resp = client.get('/system/metrics?limit=999999')
    assert resp.status_code == 200


def test_metrics_empty_buffer_collects_on_demand(client, monkeypatch):
    monkeypatch.setattr(sr, 'system_metrics_history', FakeHistory([]))
    monkeypatch.setattr(sr.system_metrics_service, 'collect_snapshot',
                        lambda: {'ts': 'now', 'cpu': 3.0})
    data = client.get('/system/metrics').get_json()
    assert data['current'] == {'ts': 'now', 'cpu': 3.0}
    assert data['history'] == []
