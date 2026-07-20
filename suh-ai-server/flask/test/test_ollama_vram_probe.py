"""GPU 실측 VRAM 조회 및 고아 런너 카운트 테스트

/api/ps는 Ollama가 인식하는 모델만 보고하므로, 실측 VRAM과 고아 런너 수를
별도로 노출해야 유령 점유를 진단할 수 있다.
"""
import subprocess

import pytest

from service.ollama_service import OllamaService


@pytest.fixture
def service():
    return OllamaService()


def _fake_run(stdout, returncode=0):
    def run(*args, **kwargs):
        return subprocess.CompletedProcess(args=args, returncode=returncode, stdout=stdout, stderr='')
    return run


def test_gpu_usage_parses_nvidia_smi(service, monkeypatch):
    monkeypatch.setattr(subprocess, 'run', _fake_run('6542, 8188\n'))
    gpu = service.get_gpu_vram_usage()
    assert gpu['available'] is True
    assert gpu['used_mb'] == 6542
    assert gpu['total_mb'] == 8188
    assert gpu['usage_percent'] == 79.9


def test_gpu_usage_unavailable_when_nvidia_smi_missing(service, monkeypatch):
    """GPU 미탑재 환경에서도 예외 없이 available=False로 떨어져야 한다 (fail-open)"""
    def boom(*args, **kwargs):
        raise FileNotFoundError('nvidia-smi not found')
    monkeypatch.setattr(subprocess, 'run', boom)
    assert service.get_gpu_vram_usage() == {'available': False}


def test_gpu_usage_unavailable_on_nonzero_exit(service, monkeypatch):
    monkeypatch.setattr(subprocess, 'run', _fake_run('', returncode=9))
    assert service.get_gpu_vram_usage() == {'available': False}


def test_orphan_runner_count_detects_extra_runners(service, monkeypatch):
    """런너 3개 - 인식 모델 1개 = 고아 2개"""
    monkeypatch.setattr('platform.system', lambda: 'Windows')
    monkeypatch.setattr(subprocess, 'run', _fake_run(
        'llama-server.exe   167780 Console   1   3,700 K\n'
        'llama-server.exe   168892 Console   1   2,320,964 K\n'
        'llama-server.exe   263348 Console   1   1,100,000 K\n'
    ))
    monkeypatch.setattr(service, 'get_vram_loaded_models', lambda: [{'model': 'gemma3:4b'}])
    assert service.get_orphan_runner_count() == 2


def test_orphan_runner_count_zero_when_matched(service, monkeypatch):
    """런너 수와 인식 모델 수가 같으면 고아 없음"""
    monkeypatch.setattr('platform.system', lambda: 'Windows')
    monkeypatch.setattr(subprocess, 'run', _fake_run(
        'llama-server.exe   168892 Console   1   2,320,964 K\n'
    ))
    monkeypatch.setattr(service, 'get_vram_loaded_models', lambda: [{'model': 'gemma3:4b'}])
    assert service.get_orphan_runner_count() == 0


def test_orphan_runner_count_skips_non_windows(service, monkeypatch):
    monkeypatch.setattr('platform.system', lambda: 'Darwin')
    assert service.get_orphan_runner_count() == 0
