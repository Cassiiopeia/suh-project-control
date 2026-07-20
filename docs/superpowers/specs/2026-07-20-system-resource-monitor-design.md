# 시스템 리소스 모니터 설계 (대시보드 시스템 오버뷰)

- 날짜: 2026-07-20
- 상태: 승인됨 (B안: 백그라운드 폴러 + 히스토리 그래프)
- 배경: 같은 머신에서 Ollama·팰월드 서버·TTS(docker)가 함께 돌아 리소스 상황 파악이 필요.
  단, 모니터링 자체가 리소스를 잡아먹지 않아야 한다.

## 목표

관리자 대시보드(`/admin`)에 CPU·메모리·디스크·GPU(사용률/VRAM/온도/전력) 현재값과
최근 2시간 추이 스파크라인을 표시한다. 수집 부하는 평균 CPU 한 코어의 0.5% 미만,
RAM 수백 KB, 디스크 5MB 상한으로 제한한다.

## 아키텍처

팰월드 메트릭 히스토리와 동일한 구조를 재사용한다:

```
[SystemMetricsPoller (daemon thread, 10s)]
   └─ collect_snapshot()  ── psutil (CPU/MEM/DISK) + nvidia-smi 1회 (GPU)
        └─ MetricsHistory (deque 720 + logs/system-metrics.jsonl, 5MB 회전)
[GET /system/metrics?limit=N]  ← 라우터는 버퍼 조회만 (추가 수집 없음)
[dashboard.js]  ← 10초 폴링, document.hidden이면 스킵
```

## 컴포넌트

### 1. `service/metrics_history.py` (리팩토링: 팰월드에서 범용화)
`PalworldMetricsHistory`의 링버퍼+jsonl 회전 로직은 팰월드 고유 로직이 없으므로
범용 `MetricsHistory` 클래스로 추출한다. `palworld_metrics_history.py`는
`MetricsHistory`를 import해 기존 공개 API(`add`, `add_from_metrics`, `history`,
싱글턴 `metrics_history`)를 유지한다. 기존 테스트가 그대로 통과해야 한다.

### 2. `config/system_config.py` (신규)
```python
SYSTEM_METRICS_HISTORY_FILE   # <flask>/logs/system-metrics.jsonl (OS 무관 상대 기준)
SYSTEM_METRICS_HISTORY_MAXLEN = 720    # 10초 × 720 = 2시간
SYSTEM_METRICS_HISTORY_MAX_BYTES = 5MB
SYSTEM_POLL_INTERVAL_SECONDS = 10
NVIDIA_SMI_TIMEOUT_SECONDS = 3
CPU_TEMP_INTERVAL_SECONDS = 60         # WMI 지원 시에만 사용
```
경로는 `C:\` 하드코딩 없이 flask 디렉토리 기준으로 계산한다
(팰월드 `C:\AI\palworld` 리터럴이 리눅스에서 상대경로 디렉토리로 커밋된 사고 재발 방지).

### 3. `service/system_metrics_service.py` (신규)
- `collect_snapshot() -> dict` — 평평한(flat) 키 구조:
  ```json
  {"ts": "...", "cpu": 12.3, "cpu_cores": 24, "cpu_temp": null,
   "mem": 33.3, "mem_used_gb": 21.3, "mem_total_gb": 64.0,
   "disk": 55.0, "disk_used_gb": 512.0, "disk_total_gb": 931.5,
   "gpu_name": "...", "gpu": 55.0, "gpu_temp": 62, "gpu_power_w": 180,
   "vram_used_mb": 12000, "vram_total_mb": 24576}
  ```
- CPU/MEM/DISK: psutil (`cpu_percent(interval=None)`, `virtual_memory`,
  `disk_usage(루트 드라이브)`). 프로세스 내 조회라 비용 0에 수렴.
- GPU: `nvidia-smi --query-gpu=name,utilization.gpu,memory.used,memory.total,temperature.gpu,power.draw
  --format=csv,noheader,nounits` subprocess, timeout 3초.
  `FileNotFoundError`(미설치)면 플래그를 세워 이후 재시도하지 않는다.
  실패 시 gpu_* 키 생략 → 프론트는 "GPU 미감지" 표시.
- CPU 온도: Windows 표준 API 부재. 기동 시 PowerShell
  `Get-CimInstance root/wmi MSAcpi_ThermalZoneTemperature` 1회 프로브,
  미지원(데스크톱 대부분)이면 영구 비활성. 지원 시에만 60초 간격 캐시 수집.
- `SystemMetricsPoller` — `palworld_event_poller` 패턴의 데몬 스레드,
  10초마다 snapshot → history 적재. 틱 예외는 삼켜 스레드 생존 보장.
- 싱글턴 `system_metrics_history = MetricsHistory(...)` 동일 파일에 정의.

### 4. `router/system_router.py` (신규)
- `GET /system/metrics?limit=120` → `{"current": {...}, "history": [...]}`
  - current: 히스토리 마지막 포인트. 버퍼가 비어 있으면(기동 직후/dev 모드)
    on-demand로 1회 수집해 반환.
  - history: 최근 limit개 (기본 120 = 20분, 최대 720). limit=0이면 빈 배열.
  - 인증은 기존과 동일하게 nginx X-API-Key 계층에서 처리. 라우터 자체 인증 없음.
- `app.py`에 blueprint 등록, `run.py`에서 poller 기동 (팰월드 폴러 옆).

### 5. 프론트엔드
- `sparkline()` 헬퍼를 `palworld.js` → `admin-common.js`로 이동 (전역 재사용).
  palworld.js는 이동된 전역 함수를 그대로 호출 (동작 불변).
- `static/js/dashboard.js` 신규: 기존 dashboard.html 인라인 스크립트를 옮기고
  시스템 리소스 로직 추가. 10초 `setInterval`, `document.hidden`이면 fetch 스킵.
- `dashboard.html`: stats 줄 아래 "시스템 리소스" 카드 1개.
  - 타일 4개(2×2, 모바일 1열): CPU(% + 온도 배지) / 메모리(% + used/total GB)
    / GPU(사용률% + 온도 + 전력) / VRAM(used/total GB) — 각 타일에 스파크라인.
  - 하단에 디스크 사용량 progress 바 1줄 (스파크라인 없음).
  - daisyUI 네이티브 컴포넌트만 사용, 커스텀 CSS 금지. 라이트/다크 토큰 준수.
  - GPU 미감지 시 GPU/VRAM 타일에 "미감지" 뱃지, CPU 온도 미지원 시 온도 배지 숨김.

### 6. 의존성
- `requirements.txt`에 `psutil` 추가 (Windows 배포 환경 pip 설치 가능).

## 에러 처리

- 수집 부분 실패는 해당 키 생략/null — 엔드포인트는 항상 200.
- 폴러 틱 예외는 로그 warning 후 계속 (기존 폴러 패턴).
- jsonl 손상 라인은 로드 시 건너뜀 (MetricsHistory 기존 동작).

## 테스트

- `test_metrics_history.py`(기존 팰월드 테스트 유지) — 리팩토링 후 그대로 통과.
- `test_system_metrics_service.py` — nvidia-smi 출력 파싱, 미설치 플래그,
  psutil mock 기반 snapshot 구조 검증.
- `test_system_router.py` — current/history 응답 형태, limit 클램프,
  빈 버퍼 on-demand 폴백.

## 리소스 예산 (승인 근거)

- nvidia-smi 10초 1회 ≈ CPU 30ms → 한 코어 ~0.3%. NVML 조회라 GPU 연산 무영향.
- 링버퍼 720 × ~120B ≈ 90KB, jsonl 5MB 상한 회전.
- 대시보드 미접속 시 프론트 폴링 0 (백그라운드 폴러만 유지).

## 범위 제외 (다음 이슈 후보)

- CPU 온도용 LibreHardwareMonitor 연동
- 프로세스별(Ollama/팰월드/docker) 리소스 분해 표시
- 임계치 알림 (온도/VRAM 초과 시 경고)
