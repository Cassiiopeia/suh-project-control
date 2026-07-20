"""test_system_metrics_service.py — 시스템 리소스 수집 (psutil/nvidia-smi mock)"""
import subprocess
from types import SimpleNamespace

import pytest

import service.system_metrics_service as sms


@pytest.fixture
def service():
    return sms.SystemMetricsService()


def _completed(stdout, returncode=0):
    return SimpleNamespace(stdout=stdout, stderr='', returncode=returncode)


def test_collect_snapshot_core_fields_without_gpu(service, monkeypatch):
    monkeypatch.setattr(service, '_query_gpu', lambda: None)
    monkeypatch.setattr(service, '_cpu_temp', lambda: None)
    point = service.collect_snapshot()
    for key in ('ts', 'cpu', 'cpu_cores', 'mem', 'mem_used_gb', 'mem_total_gb',
                'disk', 'disk_used_gb', 'disk_total_gb'):
        assert key in point, key
    assert 'gpu_name' not in point
    assert 'cpu_temp' not in point


def test_collect_snapshot_merges_gpu_and_cpu_temp(service, monkeypatch):
    monkeypatch.setattr(service, '_query_gpu', lambda: {'gpu_name': 'RTX', 'gpu': 55.0})
    monkeypatch.setattr(service, '_cpu_temp', lambda: 47.5)
    point = service.collect_snapshot()
    assert point['gpu_name'] == 'RTX'
    assert point['gpu'] == 55.0
    assert point['cpu_temp'] == 47.5


def test_query_gpu_parses_csv(service, monkeypatch):
    out = 'NVIDIA GeForce RTX 4090, 55, 12000, 24576, 62, 180.25\n'
    monkeypatch.setattr(subprocess, 'run', lambda *a, **k: _completed(out))
    gpu = service._query_gpu()
    assert gpu == {
        'gpu_name': 'NVIDIA GeForce RTX 4090', 'gpu': 55.0,
        'vram_used_mb': 12000.0, 'vram_total_mb': 24576.0,
        'gpu_temp': 62.0, 'gpu_power_w': 180.25,
    }


def test_query_gpu_handles_na_fields(service, monkeypatch):
    out = 'NVIDIA GeForce RTX 4090, 55, 12000, 24576, 62, [N/A]\n'
    monkeypatch.setattr(subprocess, 'run', lambda *a, **k: _completed(out))
    gpu = service._query_gpu()
    assert gpu['gpu_power_w'] is None
    assert gpu['gpu'] == 55.0


def test_query_gpu_multi_gpu_uses_first_line(service, monkeypatch):
    out = 'RTX 4090, 55, 12000, 24576, 62, 180\nRTX 3090, 10, 500, 24576, 40, 90\n'
    monkeypatch.setattr(subprocess, 'run', lambda *a, **k: _completed(out))
    assert service._query_gpu()['gpu_name'] == 'RTX 4090'


def test_query_gpu_nonzero_returncode(service, monkeypatch):
    monkeypatch.setattr(subprocess, 'run', lambda *a, **k: _completed('', returncode=1))
    assert service._query_gpu() is None


def test_nvidia_missing_disables_further_calls(service, monkeypatch):
    calls = []

    def raise_missing(*a, **k):
        calls.append(1)
        raise FileNotFoundError

    monkeypatch.setattr(subprocess, 'run', raise_missing)
    assert service._query_gpu() is None
    assert service._query_gpu() is None
    assert len(calls) == 1, 'nvidia-smi 미설치면 재시도하지 않아야 한다'


def test_cpu_temp_unsupported_probes_once(service, monkeypatch):
    calls = []

    def read_none():
        calls.append(1)
        return None

    monkeypatch.setattr(service, '_read_cpu_temp_wmi', read_none)
    assert service._cpu_temp() is None
    assert service._cpu_temp() is None
    assert len(calls) == 1, 'WMI 미지원이면 재프로브하지 않아야 한다'


def test_cpu_temp_supported_caches_within_interval(service, monkeypatch):
    calls = []

    def read_temp():
        calls.append(1)
        return 45.0

    monkeypatch.setattr(service, '_read_cpu_temp_wmi', read_temp)
    assert service._cpu_temp() == 45.0
    assert service._cpu_temp() == 45.0  # 60초 내 재호출 — 캐시 사용
    assert len(calls) == 1


def test_read_cpu_temp_wmi_converts_decikelvin(monkeypatch):
    # 3182 (0.1K) → 45.05°C
    monkeypatch.setattr(subprocess, 'run', lambda *a, **k: _completed('3182\n'))
    assert sms.SystemMetricsService._read_cpu_temp_wmi() == pytest.approx(45.1, abs=0.1)


def test_poller_tick_appends_snapshot(tmp_path):
    from service.metrics_history import MetricsHistory

    class OkService:
        def collect_snapshot(self):
            return {'ts': 't0', 'cpu': 1.0}

    history = MetricsHistory(str(tmp_path / 's.jsonl'), maxlen=10)
    poller = sms.SystemMetricsPoller(service=OkService(), history=history, interval=0)
    poller._tick()
    assert history.history() == [{'ts': 't0', 'cpu': 1.0}]


def test_poller_run_survives_collect_failure(tmp_path):
    from service.metrics_history import MetricsHistory

    history = MetricsHistory(str(tmp_path / 's.jsonl'), maxlen=10)
    poller = sms.SystemMetricsPoller(service=None, history=history, interval=0)

    class BoomService:
        def collect_snapshot(self):
            poller._stop.set()  # 한 틱만 돌고 종료
            raise RuntimeError('boom')

    poller._service = BoomService()
    poller._run()  # 예외를 삼키고 정상 종료해야 한다
    assert history.history() == []
