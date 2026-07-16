# 모델 관리 페이지 설계 (HF → Ollama 다운로드·관리·벤치마크)

- 날짜: 2026-07-16
- 상태: 설계 확정 (사용자 승인 대기)
- 대상: `suh-ai-server` Flask 관리 허브

## 1. 배경과 목표

suh-ai-server는 로컬 Ollama(127.0.0.1:11434)로 OCR·Vision API를 제공하고, DaisyUI 기반 관리 허브(`/admin`)에서 팰월드·로그 페이지를 운영 중이다. Ollama 공식 라이브러리는 모델 수가 적어 선택폭이 좁다.

Ollama는 `POST /api/pull`에 `hf.co/{계정}/{레포}:{양자화}` 형식을 주면 Hugging Face 허브의 공개 GGUF 모델을 직접 받아올 수 있다. 이를 이용해 관리 허브에 **모델 관리 페이지**를 추가한다:

1. HF에서 GGUF 모델 검색 → Ollama로 다운로드(진행률 표시·취소 가능)
2. 설치된 모델 목록 관리(조회·삭제)
3. 설치된 모델 즉시 테스트 + **여러 모델 비교 벤치마크**(텍스트·vision 모두)

pull 받은 모델은 기존 `/ocr/*`·`/vision/*` API의 `model` 파라미터로 즉시 사용 가능하다 — 별도 등록 절차 없음.

## 2. 범위

### 포함

- `/admin/models` 페이지 (설치 목록 / HF 검색·다운로드 / 테스트·벤치마크)
- 다운로드 진행률 실시간 표시 + 취소
- 설치 모델 삭제(확인 모달)
- 단일 모델 테스트: 이미지(업로드/URL)+프롬프트 → OCR/Vision, 텍스트 모델은 채팅 테스트
- 벤치마크 비교 실행기: 같은 입력을 여러 모델에 순차 실행 → 결과·응답시간 나란히 비교 (판단은 사람이 함)
- 기존 하드코딩 `SUPPORTED_MODELS` / `SUPPORTED_VISION_MODELS` 목록을 동적 조회로 대체

### 제외 (YAGNI)

- HF gated 모델(로그인/토큰 필요) — 공개 모델만. gated 레포를 만나면 안내 메시지만 표시
- Modelfile 커스텀 모델 생성
- 자동 채점 벤치마크(정답 등록·정확도 산출·이력 DB) — 비교 실행기 위에 나중에 얹을 수 있는 구조로만 남김
- 모델별 파라미터(temperature 등) 조정 UI

## 3. 화면 구성 (`templates/admin/models.html` + `static/js/models.js`)

기존 admin 패턴 준수: `admin/base.html` 상속, DaisyUI native 컴포넌트 우선, 바닐라 JS, `{{ asset(...) }}` 캐시 버스팅. 사이드바에 "모델 관리" 메뉴 추가.

### 3-1. 설치된 모델 (테이블)

- 컬럼: 이름, 크기, 패밀리/파라미터 수, 양자화, 수정일, vision 뱃지, 삭제 버튼
- vision 뱃지: Ollama `/api/show`의 `capabilities`에 `vision` 포함 여부로 판별
- 삭제는 DaisyUI 확인 모달 후 실행

### 3-2. HF 모델 검색·다운로드

- 검색어 입력 → GGUF 필터 결과 목록(모델명·다운로드수·좋아요·업데이트일, 다운로드수 내림차순)
- 레포 선택 → 그 레포의 GGUF 파일 목록(양자화 태그·파일 크기) 표시
- 양자화 선택 후 "가져오기" → 진행률 바(% + 받은 용량/전체 용량) 실시간 갱신
- **취소 버튼**: 스트리밍 연결을 끊으면 Ollama가 다운로드를 중단. 부분 다운로드는 Ollama가 캐시하므로 재시도 시 이어받기 됨
- 다운로드 중 페이지를 벗어나도 서버는 안전(취소와 동일하게 중단·이어받기 가능)

### 3-3. 테스트 · 벤치마크 실행기

하나의 실행기로 단일 테스트와 벤치마크를 겸한다:

- 입력: **프롬프트(필수)** + **이미지(선택** — 파일 업로드 또는 URL**)**
- 모델 선택: 설치 모델 체크박스 목록
  - 이미지가 첨부되면 vision 지원 모델만 선택 가능(나머지 비활성)
  - 이미지가 없으면 전체 모델 선택 가능(텍스트 채팅 비교)
- 실행: 선택 모델을 **한 번에 하나씩 순차 실행** (여러 모델 동시 로드로 인한 메모리 폭주 방지). 모델 하나 끝날 때마다 비교 표에 행 추가
- 비교 표: 모델명 | 결과 텍스트 | 응답 시간(초) | 상태(성공/실패)
- 모델 1개만 선택하면 그대로 단일 테스트가 됨 — 별도 UI 불필요

## 4. 백엔드

신규 2파일, 기존 router/service 분리 패턴 준수:

- `router/model_router.py` — Blueprint `model_bp`, `app.py`에 등록
- `service/model_service.py` — Ollama API·HF Hub API 클라이언트

| 엔드포인트 | 동작 |
|-----------|------|
| `GET /models/installed` | Ollama list + 모델별 show로 vision capability 병합 |
| `GET /models/search?q=<검색어>` | HF `GET https://huggingface.co/api/models?filter=gguf&search=...&sort=downloads` (인증 불필요) |
| `GET /models/hf/files?repo=<repo_id>` | HF 레포 파일 목록에서 `.gguf` 파일·크기·양자화 태그 추출 |
| `POST /models/pull` | body `{"name": "hf.co/..." }` → Ollama pull 스트리밍 프록시(진행률 JSON 라인 중계, `X-Accel-Buffering: no` 헤더로 nginx 버퍼링 해제). 클라이언트 연결이 끊기면 업스트림 스트림도 닫아 다운로드 중단 |
| `DELETE /models/installed?name=<모델명>` | Ollama delete |

- **텍스트 테스트·벤치마크는 기존 `POST /ollama/chat` 재사용** (2026-07-16 Structured Output 테스트 페이지에서 추가됨 — 응답에 `total_duration_ms` 등 메트릭 포함, 신규 test-chat 엔드포인트 불필요)
- 이미지 테스트·벤치마크는 기존 `/ocr/base64`·`/ocr/url` 재사용 (`model` 파라미터 지원)
- URL 프리픽스는 기존 스타일(`/ollama/*`, `/ocr/*`)에 맞춰 `/models/*` — nginx `/api/flask/` location이 그대로 프록시하므로 nginx 수정 불필요
- 응답 시간: 텍스트는 Ollama 메트릭 사용, 이미지는 프론트에서 요청 전후 측정
- 모델명에 `/`·`:`가 포함되므로 삭제·조회는 path variable 대신 query parameter 사용

### 기존 코드 개선

- `config/app_config.py`의 `SUPPORTED_MODELS`·`SUPPORTED_VISION_MODELS` 하드코딩 목록 제거 (grep 확인 결과 정의만 있고 참조하는 코드 없음 — 단순 삭제)
- `DEFAULT_MODEL`·`DEFAULT_VISION_MODEL`은 유지(기본값은 여전히 필요)

## 5. 에러 처리

| 상황 | 처리 |
|------|------|
| vision GGUF pull 실패 (mmproj 분리형·샤딩 레포 등 Ollama 미지원 구조) | pull 스트림의 Ollama 에러 메시지 노출 + "이 레포는 Ollama 직접 가져오기를 지원하지 않는 구조일 수 있습니다" 안내 |
| gated 모델 (401/403) | "HF 승인이 필요한 모델입니다 — 공개 모델만 지원" 안내 |
| 디스크 부족·네트워크 오류 | Ollama 에러 메시지를 토스트로 표시, 재시도 가능(이어받기) |
| 벤치마크 중 특정 모델 실패 | 그 행만 실패로 표시하고 다음 모델 계속 진행 |
| Ollama 서버 다운 | 페이지 로드 시 설치 목록 조회 실패 → 연결 오류 배너 표시 |

## 6. 테스트

기존 `test/` 패턴(pytest + mock) 준수, Ollama·HF 호출은 전부 mock:

- `test_model_service.py`: HF 검색 응답 파싱, GGUF 파일 목록 추출, vision capability 판별
- `test_model_router.py`: 설치 목록, 검색, pull 스트림 중계(진행률 라인 통과), 삭제, test-chat, 에러 케이스(gated 403, Ollama 다운)

## 7. 구현 시 검증 항목

- 실제 HF vision GGUF 레포 2~3개로 `hf.co/...` pull 성공/실패 케이스 확인 (텍스트 GGUF는 확실히 동작, vision은 레포 구조에 따라 다름)
- pull 취소 시 Flask 스트리밍 프록시가 업스트림 연결을 실제로 닫는지 확인 (WSGI 서버의 클라이언트 단절 감지 동작)
