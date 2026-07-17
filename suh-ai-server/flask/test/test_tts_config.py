"""test_tts_config.py — 엔진 레지스트리 무결성 검증"""
import os

from config.tts_config import TTS_ENGINES, TTS_REFS_DIR

REQUIRED_KEYS = {'name', 'description', 'image', 'container', 'port',
                 'adapter', 'languages', 'vram', 'docker_args', 'command', 'voices'}


def test_engines_have_required_keys():
    assert set(TTS_ENGINES) == {'kokoro', 'cosyvoice'}
    for spec in TTS_ENGINES.values():
        assert REQUIRED_KEYS <= set(spec)
        assert spec['voices'], '보이스가 최소 1개 필요'


def test_container_names_and_ports_unique():
    containers = [s['container'] for s in TTS_ENGINES.values()]
    ports = [s['port'] for s in TTS_ENGINES.values()]
    assert len(set(containers)) == len(containers)
    assert len(set(ports)) == len(ports)


def test_cosyvoice_ref_files_exist():
    # float32 WAV라 wave 모듈로는 못 읽는다 — RIFF 헤더로 형식 확인
    for voice in TTS_ENGINES['cosyvoice']['voices']:
        path = os.path.join(TTS_REFS_DIR, voice['file'])
        assert os.path.isfile(path)
        with open(path, 'rb') as f:
            head = f.read(12)
        assert head[:4] == b'RIFF' and head[8:12] == b'WAVE'


def test_cosyvoice_has_sample_rate():
    # 서버가 헤더 없는 raw PCM을 반환하므로 WAV 래핑에 필수
    assert TTS_ENGINES['cosyvoice']['sample_rate'] == 24000
