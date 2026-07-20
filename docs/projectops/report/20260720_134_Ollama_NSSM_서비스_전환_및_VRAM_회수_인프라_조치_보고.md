# [인프라 조치] Ollama NSSM 서비스 전환 및 VRAM 회수 실서버 작업 보고 (#134)

## 개요

앞선 코드 수정(v2.0.69) 배포 이후, 실서버에 남아 있던 고아 런너를 정리하고 Ollama를 유저 세션 프로세스에서 **NSSM 관리 서비스로 전환**했습니다.

작업 도중 **모델 저장소 경로 불일치**라는 별도의 결함이 발견되어 함께 해결했습니다. 이 문제를 놓쳤다면 "서비스는 Running인데 모델은 0개"인, 이전보다 더 나쁜 상태로 방치될 뻔했습니다.

이 보고서는 **코드 변경이 아닌 실서버 인프라 조치**에 대한 기록입니다.

---

## 1. 조치 전 상태

| 항목 | 값 |
|------|-----|
| VRAM 사용 | 6542 MiB / 8188 MiB (80%) |
| 고아 `llama-server.exe` | 1개 (PID 167780) |
| `/api/ps` 인식 모델 | 0개 |
| 구동 방식 | 유저 세션 프로세스 (`ollama app.exe` PID 246020, `ollama.exe` PID 37564) |
| `OllamaService` | STOPPED (`SERVICE_EXIT_CODE 3`) |

`/api/ps`는 모델이 0개라고 보고하는데 VRAM은 6.5GB가 점유된 상태였습니다. 배포한 신규 모니터링 지표가 이 불일치(`orphan_runners: 1`)를 정확히 검출했습니다.

---

## 2. 발견 및 해결한 결함

### ① NSSM 실행 경로가 LocalSystem에서 해석 불가

`OllamaService`의 실행 경로가 `%LOCALAPPDATA%\Programs\Ollama\ollama.exe`로 등록되어 있었습니다. 서비스는 LocalSystem 계정으로 기동되므로 이 변수가 `C:\Windows\System32\config\systemprofile\...`로 해석되어 **바이너리를 찾지 못해 시작에 실패**했습니다 (`SERVICE_EXIT_CODE 3`).

절대경로로 교정했습니다.

```
Application     : C:\Users\chan4\AppData\Local\Programs\Ollama\ollama.exe
AppParameters   : serve
AppDirectory    : C:\Users\chan4\AppData\Local\Programs\Ollama
```

### ② 모델 저장소 경로 불일치 (작업 중 발견)

경로 교정 후 서비스는 정상 기동했으나, **인식 모델이 0개**였습니다.

실제 모델 자산은 `C:\AI\.ollama`(blob 125개 + manifests)에 있었으나, LocalSystem 계정은 기본 탐색 경로로 빈 디렉토리를 참조하고 있었습니다. 후보 경로들의 blob 개수를 직접 대조해 실제 위치를 특정했습니다.

| 경로 | blob 수 |
|------|--------|
| `C:\AI\.ollama` | **125** (실제 자산) |
| `C:\Windows\System32\config\systemprofile\.ollama\models` | 40 |
| `C:\Users\chan4\.ollama\models` | 0 (빈 디렉토리) |
| `C:\AI\.ollama\models` | 0 (빈 디렉토리) |

`OLLAMA_MODELS`를 실제 경로로 지정해 해결했습니다.

```
AppEnvironmentExtra:
  OLLAMA_HOST=0.0.0.0:11434
  OLLAMA_MODELS=C:\AI\.ollama
```

---

## 3. 수행 절차

1. **사전 안전 확인** — 포트 11434 활성 연결(ESTABLISHED) 0건 확인 후 진행 (진행 중인 추론 중단 방지)
2. NSSM 실행 경로·작업 디렉토리·파라미터 교정
3. NSSM 환경변수 주입 (`OLLAMA_HOST`, `OLLAMA_MODELS`)
4. 기존 유저 세션 프로세스 종료 — `ollama app.exe`, `ollama.exe`, 고아 `llama-server.exe`
5. `OllamaService` 기동 및 검증

---

## 4. 조치 후 상태 및 검증

| 항목 | 조치 전 | 조치 후 |
|------|--------|--------|
| VRAM 사용 | 6542 MiB (80%) | **296 MiB (3.6%)** |
| 고아 런너 | 1개 | **0개** |
| 인식 모델 | 0개 | **42개** |
| 구동 방식 | 유저 세션 프로세스 | **OllamaService (NSSM)** |
| 서비스 상태 | STOPPED | **Running / AUTO_START** |

### 동작 검증 결과

- **추론 정상 동작**: `gemma3:1b` 생성 요청 → 정상 응답 수신
- **`keep_alive: 0` 실효 확인**: 추론 직후 `/api/ps` 즉시 비워짐, 런너 0개, VRAM 296MiB로 회수. **v2.0.69의 핵심 수정이 실서버에서 정상 작동함을 확인**
- **전체 경로 통과**: `11435(Nginx) → Flask → Ollama` 경유 `/ollama/status` 정상 응답
- **복원력 확보**: `AUTO_START` 등록으로 재부팅 시 자동 기동, 크래시 시 NSSM 자동 재기동

---

## 5. 운영상 변경점 (참고)

유저 세션 트레이 앱(`ollama app.exe`)을 종료했으므로, **윈도우에 직접 로그인해도 트레이 아이콘이 표시되지 않습니다.** Ollama는 백그라운드 서비스로 상시 구동되며 기능상 차이는 없습니다.

서비스 방식 전환으로 다음 이점이 확보되었습니다.

- 사용자 로그아웃과 무관하게 상시 구동
- 프로세스 비정상 종료 시 NSSM이 자동 복구
- Flask(LocalSystem)에서 `Start-Service` / `Stop-Service`로 정상 제어 가능 — 기존에는 서비스명 불일치로 항상 실패하여 `taskkill` 폴백에 의존했고, 이것이 고아 런너 잔존의 근본 원인이었음

---

## 6. 잔여 참고 사항

해당 서버는 데스크톱 세션이 함께 구동 중입니다(Chrome 다수 프로세스, Steam, Sunshine, Cursor, Docker Desktop 등). 이들이 8GB VRAM 중 일정량을 상시 점유하므로, 4GB 내외 대형 모델 벤치마크 시에는 여유 용량을 고려해야 합니다. 필요 시 벤치마크 전 데스크톱 앱 종료를 권장합니다.
