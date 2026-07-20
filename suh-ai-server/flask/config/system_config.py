"""
시스템 리소스 모니터 설정 (대시보드 CPU/메모리/디스크/GPU 카드)
경로는 flask 디렉토리 기준으로 계산한다 — 절대경로 리터럴을 쓰면 다른 OS에서
상대 디렉토리로 오생성된다 (팰월드 C:\\AI\\palworld 리터럴이 리눅스 실행에서
레포 안에 디렉토리로 커밋된 사고가 있었다).
"""
import os

_FLASK_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

SYSTEM_METRICS_HISTORY_FILE = os.path.join(_FLASK_DIR, 'logs', 'system-metrics.jsonl')
SYSTEM_METRICS_HISTORY_MAXLEN = 720          # 10초 간격 × 720 = 약 2시간
SYSTEM_METRICS_HISTORY_MAX_BYTES = 5 * 1024 * 1024

SYSTEM_POLL_INTERVAL_SECONDS = 10
NVIDIA_SMI_TIMEOUT_SECONDS = 3
# CPU 온도는 WMI 프로브 성공 시에만 이 간격으로 갱신 (PowerShell 호출이 무거워 제한)
CPU_TEMP_INTERVAL_SECONDS = 60
