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
        def synthesize(self, text, voice, speed, ref_wav=None):
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
        def synthesize(self, text, voice, speed, ref_wav=None):
            raise Exception('connection refused')

    monkeypatch.setattr(tts_router_module, 'get_adapter', lambda eid: DeadAdapter())
    resp = client.post('/tts', json={'text': 'hello', 'engine': 'kokoro'})
    assert resp.status_code == 503


def test_swagger_includes_tts_paths():
    from router.tts_swagger import TTS_SWAGGER_PATHS
    assert '/tts' in TTS_SWAGGER_PATHS
    assert '/tts/engines' in TTS_SWAGGER_PATHS
    assert '/tts/engines/{engine_id}/{action}' in TTS_SWAGGER_PATHS


def test_synthesize_text_length_limit(client):
    resp = client.post('/tts', json={'text': '가' * 501, 'engine': 'kokoro'})
    assert resp.status_code == 400
    assert '500' in resp.get_json()['error']


def test_voices_list_includes_builtin_and_user(client, monkeypatch):
    monkeypatch.setattr(tts_router_module.voice_store, 'list',
                        lambda: [{'id': 'u_abc12345', 'name': '내 목소리',
                                  'file': 'u_abc12345.wav', 'created_at': '2026-07-17T13:00:00'}])
    resp = client.get('/tts/voices')
    assert resp.status_code == 200
    voices = resp.get_json()['voices']
    ids = {v['id'] for v in voices}
    assert 'af_heart' in ids and 'ref_a' in ids and 'u_abc12345' in ids
    assert next(v for v in voices if v['id'] == 'u_abc12345')['builtin'] is False


def test_add_voice_requires_file(client):
    resp = client.post('/tts/voices', data={'name': 'x'})
    assert resp.status_code == 400


def test_add_voice_validation_error_400(client, monkeypatch):
    import io as _io

    def bad_add(name, blob):
        raise ValueError('WAV 형식이 아닙니다')

    monkeypatch.setattr(tts_router_module.voice_store, 'add', bad_add)
    resp = client.post('/tts/voices',
                       data={'name': 'x', 'file': (_io.BytesIO(b'zz'), 'a.wav')},
                       content_type='multipart/form-data')
    assert resp.status_code == 400


def test_add_voice_success_records_audit(client, monkeypatch):
    import io as _io
    calls = []
    monkeypatch.setattr(tts_router_module.audit_service, 'record',
                        lambda *a, **kw: calls.append(a))
    monkeypatch.setattr(tts_router_module.voice_store, 'add',
                        lambda name, blob: {'id': 'u_new12345', 'name': name,
                                            'file': 'u_new12345.wav', 'created_at': 'now'})
    resp = client.post('/tts/voices',
                       data={'name': '내 목소리', 'file': (_io.BytesIO(b'RIFF'), 'v.wav')},
                       content_type='multipart/form-data')
    assert resp.status_code == 200
    assert resp.get_json()['voice']['id'] == 'u_new12345'
    assert len(calls) == 1


def test_delete_builtin_voice_403(client):
    assert client.delete('/tts/voices/ref_a').status_code == 403


def test_delete_missing_voice_404(client, monkeypatch):
    def missing(vid):
        raise KeyError(vid)

    monkeypatch.setattr(tts_router_module.voice_store, 'delete', missing)
    assert client.delete('/tts/voices/u_nope1234').status_code == 404


def test_synthesize_multipart_oneshot_cloning(client, monkeypatch):
    import io as _io
    captured = {}

    class CloneAdapter:
        def synthesize(self, text, voice, speed, ref_wav=None):
            captured['text'] = text
            captured['ref_wav'] = ref_wav
            return b'RIFF-cloned'

    monkeypatch.setattr(tts_router_module, 'get_adapter', lambda eid: CloneAdapter())
    resp = client.post('/tts',
                       data={'text': '안녕하세요', 'engine': 'cosyvoice',
                             'prompt_wav': (_io.BytesIO(b'RIFF-ref-bytes'), 'me.wav')},
                       content_type='multipart/form-data')
    assert resp.status_code == 200
    assert resp.data == b'RIFF-cloned'
    assert captured['text'] == '안녕하세요'
    assert captured['ref_wav'] == b'RIFF-ref-bytes'


def test_synthesize_engine_not_running_friendly_message(client, monkeypatch):
    import requests as _requests

    class RefusedAdapter:
        def synthesize(self, text, voice, speed, ref_wav=None):
            raise _requests.ConnectionError('connection refused')

    monkeypatch.setattr(tts_router_module, 'get_adapter', lambda eid: RefusedAdapter())
    resp = client.post('/tts', json={'text': 'hello', 'engine': 'kokoro'})
    assert resp.status_code == 503
    assert '실행 중인지 확인' in resp.get_json()['error']
