# TTS 엔진 매니저 설계 — 관리자 화면 통합 멀티 엔진 TTS

- 날짜: 2026-07-17
- 상태: 승인됨 (대화로 설계 확정)
- 스코프: suh-ai-server에 멀티 TTS 엔진 설치·전환·테스트 기능 추가 (관리자 화면 + 외부 REST API)

## 배경 / 목표

현재 AI API는 Ollama 기반 OCR·Vision(이미지·텍스트)뿐이다. 여기에 TTS(Text-to-Speech)를 추가하되:

1. **여러 엔진을 지원**한다 — 하나만 붙이지 않고, 엔진을 갈아끼우며 비교·체험 가능
2. **관리자 화면에서 전부 관리**한다 — 설치, 시작/중지/전환, 테스트까지 (models 페이지의 TTS 버전)
3. **외부에서 REST API로 사용**한다 — 기존 `/ocr`·`/vision`과 같은 방식으로 `/tts` 공개
4. **초기 세팅까지 자동화**한다 — 기존 GitHub Actions + PowerShell 배포 파이프라인에 편입, 사용자 수동 작업 없음

## 확정된 환경 사실

| 항목 | 값 |
|---|---|
| 서버 | Windows 10 build 19045, RTX 4060 **8GB** (Ollama가 deepseek-ocr·비전 모델로 VRAM 공유 중) |
| Flask | **Windows 네이티브** NSSM 서비스 (2026-07-13 Docker 전환 설계는 미배포 — 현행 배포는 SCP + ps1 + NSSM) |
| Docker Desktop | 28.4.0, WSL2 백엔드, AutoStart=True (2026-07-13 실측) |
| 서버 접근 | 로컬 직접 SSH 불가. GitHub Actions가 시크릿(SERVER_HOST/USER/PASSWORD, 포트 2023)으로 SSH + ps1 실행 |
| 미확인 항목 | WSL2 GPU 패스스루 — 배포 스크립트 첫 단계에서 자체 검증 (아래 8절) |

## 핵심 결정 사항

1. **카탈로그 방식**: GGUF/Ollama처럼 임의 모델 자동 설치는 불가능(TTS는 모델마다 런타임이 다름).
   코드에 정의된 "지원 엔진 카탈로그"를 관리자 화면에서 설치/제어한다. 엔진 추가 = 레지스트리 항목 + 어댑터 코드 작성.
2. **초기 카탈로그 2개**:
   - **Kokoro-82M** (Kokoro-FastAPI): 영어, 초경량(~300MB), 공식 Docker 이미지 존재, OpenAI 호환 API
   - **Fun-CosyVoice3-0.5B**: 한국어 포함 9개 언어, 제로샷 보이스 클로닝 구조, 자체 FastAPI — 이미지는 공식 레포 Dockerfile 기반으로 우리가 빌드해 DockerHub(`cassiiopeia`)에 push
   - Gepard(vLLM) 등은 2단계에서 같은 틀로 추가
3. **한 번에 1개 엔진만 실행** (VRAM 8GB 보호): 다른 엔진 시작 시 실행 중 엔진을 자동 중지 (관리자 화면에서 확인 모달)
4. **엔진 제어 = docker CLI subprocess**: palworld_service가 NSSM을 subprocess로 제어하는 기존 패턴을 그대로 재사용.
   Flask는 Windows 네이티브라 `docker` CLI를 직접 호출 가능.
5. **어댑터 계층**: 엔진마다 API 형식이 달라(OpenAI 호환 vs 자체 형식) 어댑터가 `synthesize(text, voice, speed) → WAV bytes` 공통 인터페이스로 통일.
   외부 API는 엔진 교체와 무관하게 불변.

## 아키텍처

```
[관리자 화면 /admin/tts]     [외부 클라이언트]
        │                        │
        ▼                        ▼
[Flask (Windows 네이티브, NSSM, :5000)]
   ├─ router/tts_router.py   : POST /tts, GET /tts/engines, 엔진 제어 API (Swagger 문서화)
   ├─ service/tts_service.py : 엔진 수명주기 — docker CLI subprocess (설치/시작/중지/상태)
   ├─ service/tts/adapters/  : 엔진별 어댑터 (kokoro.py, cosyvoice.py)
   └─ config/tts_engines.py  : 엔진 레지스트리
        │
        ├─→ [kokoro 컨테이너 :8880]      Docker Desktop (WSL2, --gpus all)
        └─→ [cosyvoice 컨테이너 :50000]
```

### 엔진 레지스트리 (`config/tts_engines.py`)

엔진별 정의: `id`, 표시명, Docker 이미지, 호스트 포트, 어댑터 클래스, 지원 언어 목록, 예상 VRAM, 기본 보이스 목록.

### 어댑터 (`service/tts/adapters/`)

- 공통 인터페이스: `synthesize(text, voice, speed) → WAV bytes`, `health() → bool`, `list_voices() → list`
- **kokoro**: OpenAI 호환 `POST /v1/audio/speech` 호출
- **cosyvoice**: 자체 FastAPI 형식. 제로샷 클로닝 구조라 "레퍼런스 음성 클립 + 클립 텍스트"가 필요
  → 기본 레퍼런스 음성(한국어 여/남, 영어 1개)을 프로젝트 assets에 포함하고 보이스 드롭다운으로 노출

## 관리자 페이지 `/admin/tts`

기존 admin 템플릿(DaisyUI, base.html) 관례를 따른다.

- **엔진 카드 목록**: 엔진별 카드 — 상태 뱃지(미설치/중지됨/실행중/설치중), 지원 언어·VRAM 표시
  - 설치: 이미지 pull + 첫 실행 시 모델 자동 다운로드. 진행 로그는 SteamCMD 업데이트처럼 실시간 스트리밍 표시
  - 시작/중지: 실행 중 다른 엔진이 있으면 "중지 후 시작" 확인 모달
- **테스트 패널**: 실행 중 엔진 대상 — 텍스트 입력 + 보이스 드롭다운 + 속도 슬라이더 → 합성 → 오디오 플레이어 재생 + WAV 다운로드
- **상태 표시**: 실행 중 엔진 헬스체크 뱃지. 컨테이너 다운 시 명확히 표시

## 외부 API (Swagger 문서화 + 감사로그 통합)

| 엔드포인트 | 설명 |
|---|---|
| `POST /tts` | `{text, engine?, voice?, speed?}` → `audio/wav` 바이트. engine 생략 시 실행 중 엔진 사용 |
| `GET /tts/engines` | 카탈로그 + 각 엔진 상태 조회 |
| `POST /tts/engines/<id>/install` | 엔진 설치 (이미지 pull) — 관리자 전용 |
| `POST /tts/engines/<id>/start` / `stop` | 엔진 시작/중지 — 관리자 전용 |

기존 `/ocr`·`/vision`과 동일하게 nginx/API 키 정책을 따르고, 엔진 제어 행위는 감사로그(audit_service)에 기록한다.

## VRAM 공존 전략 (4060 8GB)

- 한 번에 1개 엔진 실행 원칙 (위 결정 3)
- Ollama는 idle 시 모델 자동 언로드(keep_alive) → 평상시 시분할 공존
- OOM 발생 시 죽는 것은 해당 TTS 컨테이너뿐 — OCR/Vision/팰월드 기능 무영향 (fail-open 철학 유지)
- 컨테이너 재시작 정책 `unless-stopped`

## 배포 / 초기 세팅 자동화

사용자 수동 세팅 없음. 기존 파이프라인에 편입:

1. **CosyVoice 이미지 빌드 Job** (GitHub Actions): 공식 레포 Dockerfile 기반 빌드 → DockerHub `cassiiopeia/suh-tts-cosyvoice` push (latest + git-sha 태그). Kokoro는 공식 이미지(ghcr) 사용, 빌드 불필요
2. **`scripts/deploy-tts.ps1`** (신규, deploy-flask.ps1 옆): Actions가 SSH로 실행
   - GPU 패스스루 자체 검증: `docker run --rm --gpus all <cuda이미지> nvidia-smi` — 실패 시 배포 로그에 명확한 안내 후 해당 단계만 실패 처리(다른 배포 단계는 진행)
   - 모델 캐시용 Docker 볼륨 생성(재다운로드 방지), 이미지 pull은 관리자 화면의 "설치" 버튼에서 수행(배포 시 강제 pull 하지 않음)
3. **모델 파일은 Git에 넣지 않는다** — 컨테이너가 첫 실행 시 HF에서 자동 다운로드 → 볼륨 캐시

## 에러 처리

- 실행 중 엔진 없음 → `/tts` 503 + `{"error": "실행 중인 TTS 엔진이 없습니다"}`
- 엔진 컨테이너 미응답 → 어댑터 타임아웃 → 503 + 엔진 상태 뱃지 반영
- docker CLI 실패(데몬 다운 등) → 관리자 화면에 원인 문자열 그대로 노출 (palworld 패턴)
- 설치 중 중복 요청 방지 (엔진별 설치 락)

## 테스트

- 유닛테스트(기존 test/ 관례): 어댑터 요청/응답 변환(성공/타임아웃/비정상 응답 mock), 엔진 수명주기 상태 전이(docker CLI mock), "1개만 실행" 정책
- 실 GPU 검증은 배포 후 관리자 페이지에서 스모크 테스트 (CosyVoice 한국어 합성 + Kokoro 영어 합성)

## 단계 구분

- **1단계 (이번 스코프)**: 위 전부 — Kokoro + CosyVoice, 관리자 페이지, 외부 API, 배포 자동화
- **2단계 (추후)**: 사용자 음성 업로드 보이스 클로닝, Gepard(vLLM) 엔진 추가, 스트리밍 합성, 생성 이력 관리
