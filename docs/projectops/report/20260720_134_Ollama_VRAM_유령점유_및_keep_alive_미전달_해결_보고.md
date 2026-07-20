# [버그] 벤치마크 keep_alive 미전달 및 고아 llama-server 런너로 인한 VRAM 유령 점유 해결 보고 (#134)

## 개요

Ollama 연속 벤치마크에서 발생하던 `Unexpected token '<', "<!DOCTYPE "...` 파싱 오류와 168초 지연의 실제 원인을, 시놀로지·윈도우 양쪽 서버에 직접 접속해 규명하고 해결했습니다.

기존 #127에서 "시놀로지 Nginx 60초 타임아웃이 진범"으로 진단했으나, **실측 결과 해당 진단은 현재 사실과 다릅니다.** 원인은 Nginx가 아니라 VRAM 유령 점유였습니다.

---

## 1. Nginx 오진단 정정 (실측 근거)

3개 계층을 모두 직접 확인한 결과 **전부 이미 1800초**로, Nginx는 원인이 아니었습니다.

| 계층 | 실측값 |
|------|--------|
| 시놀로지 DSM Nginx (`ai.suhsaechan.kr`) | `proxy_read_timeout 1800` |
| 윈도우 Nginx (`C:\tools\nginx-1.29.3`) | 3개 location 전부 `1800s` |
| 레포 관리본 (`suh-ai-server/config/nginx.conf`) | `1800s` — 라이브와 일치 |

추가로, 프론트에서 백엔드까지의 실제 경로가 `시놀로지 Nginx → 윈도우 Nginx(11435) → Flask(5000) → Ollama(11434)` 2단 프록시 구조임을 확인했습니다. 윈도우 Nginx는 워커 12개로 구동 중이며, 이 계층 역시 타임아웃 여유가 충분했습니다.

---

## 2. 규명한 실제 원인 4가지

### ① 벤치마크 요청이 `keep_alive`를 전달하지 않음 (핵심)

`chat()`이 Ollama에 `keep_alive`를 전혀 보내지 않아, 벤치마크가 올린 모델이 기본 정책대로 **5분간 VRAM에 상주**했습니다. 정리는 추론 완료 후 `finally`에서 별도 HTTP 요청으로 수행되어, 33개 모델 연속 실행 시 그 틈에 모델이 누적되었습니다.

### ② 고아 `llama-server.exe` 런너의 VRAM 유령 점유

`stop_ollama_daemon()`이 `taskkill /IM ollama.exe`만 실행해, 자식 추론 런너인 `llama-server.exe`가 고아로 잔존했습니다. 이 런너는 `/api/ps`에 잡히지 않으면서 VRAM을 계속 점유합니다.

**실측 증거**: `/api/ps`는 모델 1개(2.6GB)만 보고하는데 `nvidia-smi`는 6542MiB / 8188MiB 사용 중이었고, `llama-server.exe`가 2개 잔존했습니다.

### ③ 윈도우 서비스명 불일치

코드는 `Start-Service -Name Ollama`를 호출하나 NSSM 등록명은 **`OllamaService`** 입니다. 따라서 모든 서비스 제어가 실패하고 매번 `taskkill` 폴백으로 흘러 ②를 유발했습니다.

### ④ 언로드 타임아웃 3초

평상시 언로드 응답은 0.22초(실측)지만, VRAM 포화로 스와핑이 걸리면 3초를 초과해 **정리가 가장 필요한 순간에 언로드가 조용히 실패**했습니다. OOM에서 자력 회복이 불가능한 구조였습니다.

---

## 3. 조치 내역

### 벤치마크 요청에만 `keep_alive: 0` 전달

```python
chat_kwargs = {}
if auto_unload:
    chat_kwargs['keep_alive'] = 0
```

추론이 끝나는 즉시 모델이 내려가 애초에 상주하지 않습니다.

**중요 — 다른 서비스에 영향이 없습니다.** `keep_alive`는 요청 단위 파라미터이므로 vision(`gemma3:4b`, `minicpm-v4.6`), OCR(`glm-ocr`), embedding 등이 올려둔 모델은 각자의 상주 정책을 그대로 유지합니다.

> 검토 과정에서 전역 `OLLAMA_MAX_LOADED_MODELS=1` 방식도 시도했으나, **다른 서비스의 모델을 계속 밀어내는 부작용**이 확인되어 즉시 철회하고 레지스트리에서도 제거했습니다. 테스트 경로만 통제하는 현 방식이 올바른 해법입니다.

### 고아 런너 정리 및 서비스명 교정

데몬 종료 시 `llama-server.exe`까지 함께 정리하고, 서비스명을 `OllamaService`로 교정해 상수화했습니다.

### 언로드 타임아웃 30초로 확대

스와핑 구간에서도 언로드가 완주하도록 보정했습니다.

### VRAM 유령 점유 가시화 (신규)

`/ollama/status`에 `nvidia-smi` 실측값과 고아 런너 수를 추가하고, 관리 페이지에 실측 게이지를 노출했습니다.

- 사용률에 따라 색상 전환 (75% 경고 / 90% 위험)
- **모델 점유량과 실측 사용량의 차이**를 "그 외 점유"로 표시해 유령 점유를 즉시 식별
- 고아 런너 감지 시 경고 배너 표시

GPU 미탑재 환경에서도 `available: false`로 떨어져 상태 조회 전체가 막히지 않도록 fail-open 처리했습니다.

---

## 4. 검증

- **테스트 308개 전부 통과** (기존 299 + 신규 9)
  - `test_ollama_service_keepalive.py` — 벤치마크만 `keep_alive=0`이 나가고 일반 호출엔 나가지 않음을 검증
  - `test_ollama_vram_probe.py` — nvidia-smi 파싱, 고아 런너 카운트, GPU 미탑재 fail-open 검증
- Tailwind CSS 재빌드 완료 (신규 `progress-*` 클래스 purge 누락 방지)

---

## 5. 후속 확인 필요 사항

**`OllamaService`(NSSM)가 현재 시작 불가 상태입니다.** 실행 경로가 `%LOCALAPPDATA%\Programs\Ollama\ollama.exe`로 설정되어 있는데, 서비스는 LocalSystem으로 기동되므로 이 변수가 `C:\Windows\System32\config\systemprofile\...`로 해석되어 바이너리를 찾지 못합니다 (`SERVICE_EXIT_CODE 3`).

현재는 유저 세션 프로세스(`ollama app.exe`)가 대신 서비스 중이라 표면화되지 않았으나, 서비스 자동 복구가 동작하지 않는 상태입니다. 경로를 절대경로로 교정하면 해결되며, 적용 시 Ollama 재시작이 필요하므로 별도 진행을 권장합니다.

또한 해당 서버는 데스크톱 세션이 함께 구동 중이라(Chrome 15개 프로세스, Steam, Sunshine, Cursor, Docker Desktop 등) 8GB VRAM 중 상당분을 상시 점유합니다. 대형 모델 벤치마크 시에는 이 점을 고려해야 합니다.
