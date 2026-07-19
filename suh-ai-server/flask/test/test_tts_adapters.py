"""test_tts_adapters.py — 어댑터 요청/응답 변환 검증 (HTTP는 mock)"""
import io
import wave

import pytest

import service.tts.adapters as adapters
from service.tts.adapters import get_adapter


class FakeResponse:
    def __init__(self, content=b'', status_code=200):
        self.content = content
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise Exception(f'HTTP {self.status_code}')


def test_kokoro_synthesize_posts_openai_format(monkeypatch):
    captured = {}

    def fake_post(url, **kwargs):
        captured['url'] = url
        captured['json'] = kwargs['json']
        return FakeResponse(b'RIFF....WAVE')

    monkeypatch.setattr(adapters.requests, 'post', fake_post)
    wav = get_adapter('kokoro').synthesize('hello', 'af_heart', 1.2)
    assert wav == b'RIFF....WAVE'
    assert captured['url'] == 'http://127.0.0.1:8880/v1/audio/speech'
    assert captured['json'] == {'model': 'kokoro', 'voice': 'af_heart',
                                'input': 'hello', 'response_format': 'wav', 'speed': 1.2}


def test_cosyvoice_synthesize_wraps_pcm_as_wav(monkeypatch):
    pcm = b'\x00\x01' * 2400  # int16 mono 샘플 2400개
    captured = {}

    def fake_post(url, **kwargs):
        captured['url'] = url
        captured['data'] = kwargs['data']
        captured['has_file'] = 'prompt_wav' in kwargs['files']
        return FakeResponse(pcm)

    monkeypatch.setattr(adapters.requests, 'post', fake_post)
    wav_bytes = get_adapter('cosyvoice').synthesize('안녕하세요', 'ref_a', 1.0)
    assert captured['url'] == 'http://127.0.0.1:50000/inference_cross_lingual'
    assert captured['data'] == {'tts_text': '안녕하세요'}
    assert captured['has_file'] is True
    with wave.open(io.BytesIO(wav_bytes)) as w:
        assert w.getframerate() == 24000
        assert w.getnchannels() == 1
        assert w.getsampwidth() == 2
        assert w.getnframes() == 2400


def test_cosyvoice_unknown_voice_falls_back_to_first(monkeypatch):
    monkeypatch.setattr(adapters.requests, 'post', lambda url, **kw: FakeResponse(b'\x00\x00'))
    # 존재하지 않는 voice id — 예외 없이 첫 보이스로 동작해야 한다
    get_adapter('cosyvoice').synthesize('테스트', 'no-such-voice', 1.0)


def test_health_false_when_connection_fails(monkeypatch):
    def boom(url, timeout):
        raise adapters.requests.RequestException('refused')

    monkeypatch.setattr(adapters.requests, 'get', boom)
    assert get_adapter('kokoro').health() is False
    assert get_adapter('cosyvoice').health() is False


def test_get_adapter_unknown_engine_raises():
    with pytest.raises(KeyError):
        get_adapter('no-such-engine')


def test_cosyvoice_uses_user_voice_path(monkeypatch, tmp_path):
    ref = tmp_path / 'u_abc12345.wav'
    ref.write_bytes(b'RIFFxxxxWAVE')
    monkeypatch.setattr(adapters.voice_store, 'path', lambda vid: str(ref))
    captured = {}

    def fake_post(url, **kwargs):
        captured['file_name'] = kwargs['files']['prompt_wav'].name
        return FakeResponse(b'\x00\x00')

    monkeypatch.setattr(adapters.requests, 'post', fake_post)
    get_adapter('cosyvoice').synthesize('안녕', 'u_abc12345', 1.0)
    assert captured['file_name'] == str(ref)


def test_cosyvoice_deleted_user_voice_falls_back(monkeypatch):
    def missing(vid):
        raise KeyError(vid)

    monkeypatch.setattr(adapters.voice_store, 'path', missing)
    monkeypatch.setattr(adapters.requests, 'post', lambda url, **kw: FakeResponse(b'\x00\x00'))
    # 삭제된 u_* id — 예외 없이 내장 보이스로 폴백해야 한다
    get_adapter('cosyvoice').synthesize('안녕', 'u_gone9999', 1.0)


def test_supertonic_detects_korean_lang(monkeypatch):
    captured = {}

    def fake_post(url, **kwargs):
        captured['url'] = url
        captured['json'] = kwargs['json']
        return FakeResponse(b'RIFF-supertonic-wav')

    monkeypatch.setattr(adapters.requests, 'post', fake_post)
    wav = get_adapter('supertonic').synthesize('안녕하세요', 'F1', 1.0)
    assert wav == b'RIFF-supertonic-wav'
    assert captured['url'] == 'http://127.0.0.1:7788/v1/tts'
    assert captured['json'] == {'text': '안녕하세요', 'voice': 'F1', 'lang': 'ko'}


def test_supertonic_detects_english_lang(monkeypatch):
    captured = {}
    monkeypatch.setattr(adapters.requests, 'post',
                        lambda url, **kw: captured.update(kw) or FakeResponse(b'x'))
    get_adapter('supertonic').synthesize('Hello world', 'M1', 1.0)
    assert captured['json']['lang'] == 'en'


def test_qwen3tts_korean_language_and_endpoint(monkeypatch):
    captured = {}

    def fake_post(url, **kwargs):
        captured['url'] = url
        captured['json'] = kwargs['json']
        return FakeResponse(b'RIFF-qwen')

    monkeypatch.setattr(adapters.requests, 'post', fake_post)
    wav = get_adapter('qwen3tts').synthesize('안녕하세요', 'Sohee', 1.0)
    assert wav == b'RIFF-qwen'
    assert captured['url'] == 'http://127.0.0.1:7801/synthesize'
    assert captured['json'] == {'text': '안녕하세요', 'voice': 'Sohee', 'language': 'Korean'}


def test_chatterbox_ref_wav_oneshot(monkeypatch):
    captured = {}

    def fake_post(url, **kwargs):
        captured['url'] = url
        captured['data'] = kwargs['data']
        captured['has_ref'] = kwargs.get('files') is not None
        return FakeResponse(b'RIFF-cb')

    monkeypatch.setattr(adapters.requests, 'post', fake_post)
    get_adapter('chatterbox').synthesize('안녕', 'default', 1.0, ref_wav=b'RIFF-ref')
    assert captured['url'] == 'http://127.0.0.1:7802/synthesize'
    assert captured['data'] == {'text': '안녕', 'lang': 'ko'}
    assert captured['has_ref'] is True
    get_adapter('chatterbox').synthesize('hello', 'default', 1.0)
    assert captured['data']['lang'] == 'en'
    assert captured['has_ref'] is False
