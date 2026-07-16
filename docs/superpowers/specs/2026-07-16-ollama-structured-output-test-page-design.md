# Ollama Structured Output 테스트 페이지 설계

- 날짜: 2026-07-16
- 상태: 승인됨 (구현 진행)

## 목적

관리자 페이지에서 Ollama의 Structured Outputs(`format`에 JSON Schema 전달 → 디코딩 단계 강제)를
모델을 바꿔가며 직접 테스트한다. 4B급 소형 모델(gemma3:4b 등)에서 중첩 Object·배열·enum 스키마가
실제로 강제되는지, 응답 속도는 어떤지 눈으로 확인하는 것이 목표.

## 아키텍처

브라우저 → Flask(`/ollama/*`) → 내부 `ollama.Client`(127.0.0.1:11434) 경로를 사용한다.
OCR/Vision 서비스가 이미 같은 방식으로 Ollama에 직결돼 있으므로 그 패턴을 재사용한다.
(외부 호출자는 nginx `location /` 프록시로 Ollama를 직접 쓰면 되므로 별도 래핑 API는 만들지 않는다 —
이 엔드포인트는 관리자 테스트 페이지 전용 얇은 통로다.)

관리자 페이지 JS는 기존 페이지들과 동일하게 상대경로(`../ollama/*`) + `apiFetch()`(X-API-Key)로
호출한다. nginx 없이 로컬 Flask(:5000)만 띄워도 동작한다.

## 변경 파일

| 파일 | 변경 |
|------|------|
| `service/ollama_service.py` | 신규 — 모델 목록, structured chat 실행 (내부 Client 재사용 패턴) |
| `router/ollama_router.py` | 신규 — `GET /ollama/models`, `POST /ollama/chat` |
| `app.py` | 블루프린트 등록 |
| `router/admin_router.py` | `GET /admin/ollama-test` 페이지 라우트 |
| `templates/admin/ollama-test.html` | 신규 페이지 (base.html 상속) |
| `static/js/ollama-test.js` | 페이지 로직 |
| `templates/admin/base.html` | 사이드바 메뉴 항목 |
| `templates/admin/dashboard.html` | 대시보드 카드 |
| `static/css/app.css` | Tailwind 재빌드 산출물 |
| `test/test_ollama_router.py` | 라우터 단위 테스트 (Ollama 모킹) |

## API

### GET /ollama/models

Ollama에 설치된 모델 목록. 응답:

```json
{ "success": true, "models": [ { "name": "gemma3:4b", "size": 3338801718, "parameter_size": "4.3B", "family": "gemma3" } ] }
```

### POST /ollama/chat

```json
{
  "model": "gemma3:4b",            // 필수
  "prompt": "...",                  // 필수
  "system": "...",                  // 선택
  "temperature": 0,                 // 선택, 기본 0
  "format": null | "json" | {...}   // 선택 — JSON Schema 객체면 구조 강제
}
```

응답:

```json
{
  "success": true,
  "content": "{...모델 출력 문자열...}",
  "model": "gemma3:4b",
  "metrics": {
    "total_duration_ms": 2100,
    "load_duration_ms": 40,
    "prompt_eval_count": 25,
    "eval_count": 71,
    "eval_duration_ms": 1900,
    "tokens_per_second": 37.4
  }
}
```

검증: `model`·`prompt` 없으면 400. `format`이 null/"json"/object 외이면 400. Ollama 오류는 500 + 메시지.
`stream`은 항상 false (테스트 용도 단순화).

## UI

**요청 카드**
- 모델 select (`/ollama/models`, 새로고침 버튼) + temperature 입력(기본 0)
- format 모드 토글: 없음 / `"json"` / JSON Schema — 셋의 차이 비교가 페이지의 핵심
- 시스템 프롬프트(선택) / 유저 프롬프트 textarea
- 스키마 textarea(monospace) + 프리셋: 단순 객체 / 중첩 객체 / 배열 속 Object / enum 포함
- 스키마 실시간 JSON 파싱 검사 — 오류 시 실행 비활성 + 에러 메시지
- 실행 버튼: 실행 중 스피너 + 경과시간, 중복 실행 방지

**결과 누적 리스트** (최신 위)
- 모델명·format 모드 배지, 소요시간, tok/s
- `content`를 JSON.parse → 성공 시 pretty-print + "유효 JSON" 배지, 실패 시 원문 + 경고 배지
- 에러도 카드로 누적, 전체 지우기 버튼, 새로고침 시 휘발 (저장 안 함)

모델을 바꿔가며 실행 → 결과가 쌓여 자연스럽게 모델 간 비교.

## 에러 처리 / 테스트

- 401 → 기존 apiFetch 키 모달 재사용
- Ollama 미기동/모델 미존재 → 에러 카드
- pytest: 파라미터 검증(400), 정상 흐름(서비스 모킹), 페이지 렌더링 200
