"""
시스템 리소스 메트릭 수집 (CPU/메모리/디스크/GPU) + 10초 백그라운드 폴러.

수집 비용을 최소화하는 것이 설계 목표다:
- CPU/메모리/디스크: psutil 프로세스 내 조회 — 비용 사실상 0
- GPU: nvidia-smi subprocess 1회. NVML 카운터를 읽기만 하므로 GPU 연산을
  건드리지 않아 Ollama 추론 성능에 영향이 없다. 미설치면 플래그를 세워
  이후 재시도하지 않는다.
- CPU 온도: Windows 표준 API가 없어 WMI(MSAcpi_ThermalZoneTemperature)를
  첫 수집 때 1회 프로브. 미지원(데스크톱 보드 대부분)이면 영구 비활성,
  지원 시에만 CPU_TEMP_INTERVAL_SECONDS 간격으로 갱신한다.
"""
import logging
import os
import subprocess
import threading
import time
from datetime import datetime

import psutil

from config.system_config import (
    CPU_TEMP_INTERVAL_SECONDS, NVIDIA_SMI_TIMEOUT_SECONDS,
    SYSTEM_METRICS_HISTORY_FILE, SYSTEM_METRICS_HISTORY_MAX_BYTES,
    SYSTEM_METRICS_HISTORY_MAXLEN, SYSTEM_POLL_INTERVAL_SECONDS,
)
from service.metrics_history import MetricsHistory

logger = logging.getLogger(__name__)

_GPU_QUERY = 'name,utilization.gpu,memory.used,memory.total,temperature.gpu,power.draw'


def _to_float(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None  # nvidia-smi는 미지원 항목을 '[N/A]'로 준다


class SystemMetricsService:

    def __init__(self):
        self._nvidia_missing = False
        self._cpu_temp_supported = None   # None = 아직 프로브 안 함
        self._cpu_temp_value = None
        self._cpu_temp_read_at = 0.0
        # cpu_percent는 직전 호출 이후의 사용률을 주므로 기준점을 미리 만든다
        # (없으면 첫 수집이 0.0으로 나온다)
        psutil.cpu_percent(interval=None)

    def collect_snapshot(self) -> dict:
        """현재 시스템 리소스 스냅샷 하나. 실패 항목은 키를 생략한다 (flat 구조)."""
        vm = psutil.virtual_memory()
        disk = psutil.disk_usage(os.path.abspath(os.sep))
        point = {
            'ts': datetime.now().isoformat(timespec='seconds'),
            'cpu': round(psutil.cpu_percent(interval=None), 1),
            'cpu_cores': psutil.cpu_count(logical=True),
            'mem': round(vm.percent, 1),
            'mem_used_gb': round((vm.total - vm.available) / 2 ** 30, 1),
            'mem_total_gb': round(vm.total / 2 ** 30, 1),
            'disk': round(disk.percent, 1),
            'disk_used_gb': round(disk.used / 2 ** 30, 1),
            'disk_total_gb': round(disk.total / 2 ** 30, 1),
        }
        cpu_temp = self._cpu_temp()
        if cpu_temp is not None:
            point['cpu_temp'] = cpu_temp
        gpu = self._query_gpu()
        if gpu:
            point.update(gpu)
        return point

    # ---------- GPU (nvidia-smi) ----------

    def _query_gpu(self):
        if self._nvidia_missing:
            return None
        try:
            result = subprocess.run(
                ['nvidia-smi', f'--query-gpu={_GPU_QUERY}', '--format=csv,noheader,nounits'],
                capture_output=True, text=True, timeout=NVIDIA_SMI_TIMEOUT_SECONDS)
        except FileNotFoundError:
            self._nvidia_missing = True
            logger.info('nvidia-smi 미발견 — GPU 수집 비활성화')
            return None
        except Exception as e:
            logger.debug(f'nvidia-smi 실패: {e}')
            return None
        if result.returncode != 0 or not result.stdout.strip():
            return None
        # 여러 GPU면 첫 줄(첫 GPU)만. name에는 콤마가 없다.
        parts = [p.strip() for p in result.stdout.strip().splitlines()[0].split(',')]
        if len(parts) < 6:
            return None
        return {
            'gpu_name': parts[0],
            'gpu': _to_float(parts[1]),
            'vram_used_mb': _to_float(parts[2]),
            'vram_total_mb': _to_float(parts[3]),
            'gpu_temp': _to_float(parts[4]),
            'gpu_power_w': _to_float(parts[5]),
        }

    # ---------- CPU 온도 (WMI best-effort) ----------

    def _cpu_temp(self):
        if self._cpu_temp_supported is False:
            return None
        now = time.monotonic()
        if self._cpu_temp_supported and now - self._cpu_temp_read_at < CPU_TEMP_INTERVAL_SECONDS:
            return self._cpu_temp_value
        value = self._read_cpu_temp_wmi()
        if self._cpu_temp_supported is None:
            self._cpu_temp_supported = value is not None
            if not self._cpu_temp_supported:
                logger.info('WMI CPU 온도 미지원 — CPU 온도 표시 비활성화')
        self._cpu_temp_value = value
        self._cpu_temp_read_at = now
        return value

    @staticmethod
    def _read_cpu_temp_wmi():
        try:
            result = subprocess.run(
                ['powershell', '-NoProfile', '-Command',
                 '(Get-CimInstance -Namespace root/wmi -ClassName MSAcpi_ThermalZoneTemperature '
                 '-ErrorAction Stop | Select-Object -First 1).CurrentTemperature'],
                capture_output=True, text=True, timeout=10)
            raw = _to_float(result.stdout.strip())
            if result.returncode != 0 or raw is None:
                return None
            celsius = round(raw / 10.0 - 273.15, 1)  # 단위: 0.1 켈빈
            return celsius if -20 < celsius < 150 else None
        except Exception:
            return None


class SystemMetricsPoller:
    """10초마다 스냅샷을 히스토리에 적재하는 데몬 스레드 (팰월드 폴러 패턴)."""

    def __init__(self, service=None, history=None,
                 interval: int = SYSTEM_POLL_INTERVAL_SECONDS):
        self._service = service or system_metrics_service
        self._history = history if history is not None else system_metrics_history
        self._interval = interval
        self._stop = threading.Event()

    def start(self) -> threading.Thread:
        thread = threading.Thread(target=self._run, daemon=True, name='system-metrics-poller')
        thread.start()
        return thread

    def _run(self):
        while not self._stop.is_set():
            try:
                self._tick()
            except Exception as e:
                # 틱 단위로 삼켜서 스레드 생존 보장
                logger.warning(f'System metrics poller tick failed: {e}')
            self._stop.wait(self._interval)

    def _tick(self):
        self._history.add(self._service.collect_snapshot())


# 폴러(적재)와 라우터(조회)가 공유하는 단일 인스턴스
system_metrics_service = SystemMetricsService()
system_metrics_history = MetricsHistory(
    SYSTEM_METRICS_HISTORY_FILE, SYSTEM_METRICS_HISTORY_MAXLEN,
    SYSTEM_METRICS_HISTORY_MAX_BYTES)
