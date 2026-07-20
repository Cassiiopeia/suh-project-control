## 버그 현상 요약

Ollama Structured Output 연속 벤치마크 테스트 중 대형 모델 구간에서 `Unexpected token '<', "<!DOCTYPE "... is not valid JSON` 파싱 오류와 함께 168초 이상의 극심한 지연이 발생합니다.

기존 이슈 #127에서 "시놀로지 Nginx의 60초 `proxy_read_timeout`이 원인"으로 진단하고 조치했으나, **실서버 검증 결과 해당 진단은 현재 사실과 다르며 문제가 재현**되고 있습니다.

## 실서버 검증으로 규명한 실제 원인

Nginx 3개 계층을 모두 직접 확인한 결과, **Nginx는 원인이 아닙니다.**

| 계층 | 실제 설정값 | 판정 |
|------|------------|------|
| 시놀로지 DSM Nginx (`ai.suhsaechan.kr`) | `proxy_read_timeout 1800s` | 정상 |
| 윈도우 Nginx (`C:\tools\nginx-1.29.3`) | 3개 location 전부 `1800s` | 정상 |
| 레포 관리본 (`suh-ai-server/config/nginx.conf`) | `1800s` (라이브와 일치) | 정상 |

실제 원인은 다음 4가지 결함이 복합된 **VRAM 유령 점유 및 언로드 실패**입니다.

### 1. 벤치마크 요청이 `keep_alive`를 전달하지 않음 (핵심)

`ollama_service.chat()`이 Ollama에 `keep_alive` 파라미터를 전혀 보내지 않아, 벤치마크가 올린 모델이 기본 정책대로 **5분간 VRAM에 상주**합니다. 정리는 추론 완료 후 `finally`에서 별도 HTTP 요청으로 수행되어, 33개 모델 연속 실행 시 그 틈에 모델이 누적됩니다.

### 2. 고아 `llama-server.exe` 런너가 VRAM 유령 점유

`stop_ollama_daemon()`이 `taskkill /IM ollama.exe`만 실행하여 자식 프로세스인 추론 런너 `llama-server.exe`가 고아로 잔존합니다. 이 런너는 `/api/ps`에 잡히지 않으면서 VRAM을 계속 점유합니다.

실측 증거: `/api/ps`는 모델 1개(2.6GB)만 보고하는데 `nvidia-smi`는 6542MiB / 8188MiB 사용 중이었고, `llama-server.exe` 프로세스가 2개 잔존했습니다.

### 3. 윈도우 서비스명 불일치로 서비스 제어가 항상 실패

코드가 `Start-Service -Name Ollama` / `Stop-Service -Name Ollama`를 호출하나, NSSM에 등록된 실제 서비스명은 **`OllamaService`** 입니다. 따라서 모든 서비스 제어가 실패하고 매번 `taskkill` 폴백으로 흘러 위 2번 문제를 유발합니다.

### 4. 언로드 타임아웃 3초가 과도하게 짧음

`unload_vram_model()`의 요청 타임아웃이 3초입니다. 평상시 응답은 0.22초(실측)지만, VRAM 포화로 스와핑이 걸리면 이를 초과하여 **정리가 가장 필요한 순간에 언로드가 조용히 실패**합니다. OOM 상태에서 자력 회복이 불가능한 구조입니다.

## 부가 확인 사항

- `OllamaService`(NSSM)는 `AUTO_START`로 등록되어 있으나 **STOPPED** 상태이며, 실행 경로가 `%LOCALAPPDATA%\Programs\Ollama\ollama.exe`로 설정되어 있습니다. 서비스는 LocalSystem으로 기동되므로 이 변수가 `C:\Windows\System32\config\systemprofile\...`로 해석되어 **바이너리를 찾지 못해 시작에 실패**합니다 (`SERVICE_EXIT_CODE 3`). 현재는 유저 세션 프로세스가 대신 서비스 중이라 표면화되지 않았습니다.
- 관리 페이지의 VRAM 모니터는 `/api/ps`만 조회하므로 고아 런너가 점유한 VRAM이 표시되지 않아, 이번 유형의 장애를 진단할 수 없습니다.

## 조치 방향

1. 벤치마크(`auto_unload=True`) 요청에만 `keep_alive: 0`을 전달하여 추론 직후 즉시 언로드. **요청 단위 파라미터이므로 vision/OCR/embedding 등 다른 서비스가 상주시킨 모델의 정책에는 영향을 주지 않아야 합니다.** (전역 `OLLAMA_MAX_LOADED_MODELS` 설정은 타 서비스를 밀어내므로 채택 불가)
2. 데몬 종료 시 `llama-server.exe` 런너까지 함께 정리
3. 서비스명을 `OllamaService`로 교정하고 상수화
4. 언로드 타임아웃을 30초로 확대
5. VRAM 모니터에 `nvidia-smi` 실측값을 병기하여 유령 점유 가시화
