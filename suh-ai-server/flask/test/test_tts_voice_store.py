"""test_tts_voice_store.py — 사용자 보이스 저장소 CRUD·검증"""
import io
import wave

import pytest

import service.tts.voice_store as voice_store_module
from service.tts.voice_store import VoiceStore


def make_wav(seconds: float, sample_rate: int = 16000) -> bytes:
    """지정 길이의 무음 PCM16 WAV 생성"""
    buf = io.BytesIO()
    with wave.open(buf, 'wb') as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sample_rate)
        w.writeframes(b'\x00\x00' * int(sample_rate * seconds))
    return buf.getvalue()


@pytest.fixture
def store(tmp_path):
    return VoiceStore(data_dir=str(tmp_path / 'voices'))


def test_add_list_delete_roundtrip(store):
    entry = store.add('내 목소리', make_wav(5))
    assert entry['id'].startswith('u_')
    assert store.list() == [entry]
    assert store.path(entry['id']).endswith(f"{entry['id']}.wav")
    store.delete(entry['id'])
    assert store.list() == []


def test_add_rejects_non_wav(store):
    with pytest.raises(ValueError):
        store.add('x', b'not-a-wav-file-at-all-not-a-wav-file-at-all-xxxx')


def test_add_rejects_short_and_long(store):
    with pytest.raises(ValueError):
        store.add('short', make_wav(1))
    with pytest.raises(ValueError):
        store.add('long', make_wav(31))


def test_add_rejects_oversize(store, monkeypatch):
    monkeypatch.setattr(voice_store_module, 'MAX_BYTES', 1000)
    with pytest.raises(ValueError):
        store.add('big', make_wav(5))


def test_add_requires_name(store):
    with pytest.raises(ValueError):
        store.add('  ', make_wav(5))


def test_delete_missing_raises(store):
    with pytest.raises(KeyError):
        store.delete('u_nope1234')


def test_path_missing_raises(store):
    with pytest.raises(KeyError):
        store.path('u_nope1234')
