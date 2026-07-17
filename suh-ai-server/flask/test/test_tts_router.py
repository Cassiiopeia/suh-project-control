"""test_tts_router.py — /tts/* 엔드포인트 검증 (서비스·어댑터·감사로그 mock)"""
import pytest
from flask import Flask

import router.tts_router as tts_router_module
from router.tts_router import tts_bp


@pytest.fixture
def client(monkeypatch):
    # DB 접근 차단 — 감사로그는 no-op
    monkeypatch.setattr(tts_router_module.audit_service, 'record',
                        lambda *a, **kw: True)
    app = Flask(__name__)
    app.register_blueprint(tts_bp)
    return app.test_client()


def test_engines_state(client, monkeypatch):
    monkeypatch.setattr(tts_router_module.tts_service, 'get_engines_state',
                        lambda: [{'id': 'kokoro', 'status': 'stopped'}])
    resp = client.get('/tts/engines')
    assert resp.status_code == 200
    assert resp.get_json()['engines'][0]['id'] == 'kokoro'


def test_control_unknown_engine_404(client):
    assert client.post('/tts/engines/nope/start').status_code == 404


def test_control_unknown_action_404(client):
    assert client.post('/tts/engines/kokoro/explode').status_code == 404


def test_control_start_records_audit(client, monkeypatch):
    calls = []
    monkeypatch.setattr(tts_router_module.audit_service, 'record',
                        lambda *a, **kw: calls.append(a))
    monkeypatch.setattr(tts_router_module.tts_service, 'start', lambda eid: None)
    monkeypatch.setattr(tts_router_module.tts_service, 'get_engines_state', lambda: [])
    resp = client.post('/tts/engines/kokoro/start')
    assert resp.status_code == 200
    assert len(calls) == 1


def test_control_conflict_returns_409(client, monkeypatch):
    def dup(eid):
        raise ValueError('이미 설치 진행 중입니다')

    monkeypatch.setattr(tts_router_module.tts_service, 'install', dup)
    assert client.post('/tts/engines/kokoro/install').status_code == 409


def test_synthesize_requires_text(client):
    assert client.post('/tts', json={}).status_code == 400


def test_synthesize_no_running_engine_503(client, monkeypatch):
    monkeypatch.setattr(tts_router_module.tts_service, 'get_running_engine',
                        lambda: None)
    resp = client.post('/tts', json={'text': '안녕'})
    assert resp.status_code == 503


def test_synthesize_returns_wav(client, monkeypatch):
    class FakeAdapter:
        def synthesize(self, text, voice, speed):
            return b'RIFF-fake-wav'

    monkeypatch.setattr(tts_router_module.tts_service, 'get_running_engine',
                        lambda: 'kokoro')
    monkeypatch.setattr(tts_router_module, 'get_adapter', lambda eid: FakeAdapter())
    resp = client.post('/tts', json={'text': 'hello'})
    assert resp.status_code == 200
    assert resp.mimetype == 'audio/wav'
    assert resp.data == b'RIFF-fake-wav'


def test_synthesize_engine_down_503(client, monkeypatch):
    class DeadAdapter:
        def synthesize(self, text, voice, speed):
            raise Exception('connection refused')

    monkeypatch.setattr(tts_router_module, 'get_adapter', lambda eid: DeadAdapter())
    resp = client.post('/tts', json={'text': 'hello', 'engine': 'kokoro'})
    assert resp.status_code == 503


def test_swagger_includes_tts_paths():
    from router.tts_swagger import TTS_SWAGGER_PATHS
    assert '/tts' in TTS_SWAGGER_PATHS
    assert '/tts/engines' in TTS_SWAGGER_PATHS
    assert '/tts/engines/{engine_id}/{action}' in TTS_SWAGGER_PATHS
