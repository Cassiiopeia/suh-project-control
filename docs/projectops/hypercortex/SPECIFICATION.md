# SPECIFICATION

## [DATA_FLOW]

사용자가 "실행" 버튼을 클릭하여 여러 모델을 대상으로 벤치마크를 수행할 때의 클라이언트-서버 간 데이터 흐름과 상태 전이 과정을 시각화합니다.

```
+---------------------------------------------------------------------------------------------------------+
|                                              [ Client-Side ]                                            |
|                                                                                                         |
|  1. UI Event: User clicks "Run" after selecting Models [M1, M2] with JSON Schema & Prompts              |
|                                                                                                         |
|  2. Serialization Loop:                                                                                 |
|     +---------------------------------------------------------------------------------------------+     |
|     | For each model: [M1, M2]                                                                    |     |
|     |                                                                                             |     |
|     |  A. Update Progress (e.g., "M1 (1/2) is running...")                                        |     |
|     |  B. Send POST request to ../ollama/chat                                                     |     |
|     |     |                                                                                       |     |
+-----+-----+---------------------------------------------------------------------------------------+-----+
            |                                                                                       ^
            | (HTTP POST /ollama/chat)                                                              | (JSON Response)
            v                                                                                       |
+-----+-----+---------------------------------------------------------------------------------------+-----+
|     |     |                                                                                       |     |
|     |  C. Call Ollama Client API                                                                  |     |
|     |     |                                                                                       |     |
|     |     v                                                                                       |     |
|     |  D. Process ollama response, compute metrics:                                               |     |
|     |     - total_duration_ms, load_duration_ms, eval_duration_ms                                 |     |
|     |     - prompt_eval_count (Input Tokens), eval_count (Output Tokens)                          |     |
|     |     - tokens_per_second                                                                     |     |
|     |                                                                                             |     |
|     +---------------------------------------------------------------------------------------------+     |
|                                                                                                         |
|                                            [ Server-Side (Flask) ]                                      |
+---------------------------------------------------------------------------------------------------------+
```

---

## [API_SPECIFICATION]

### 1. GET `../ollama/models` (설치된 모델 목록 조회)
- **설명**: 현재 Ollama 서버에 정상적으로 설치된 모든 LLM 모델의 기본 메타데이터 목록을 받아옵니다.
- **Response 예시 (JSON)**:
  ```json
  {
    "success": true,
    "models": [
      {
        "name": "gemma3:4b",
        "size": 3338801718,
        "parameter_size": "4.3B",
        "family": "gemma3",
        "vision": false
      },
      {
        "name": "deepseek-ocr:3b",
        "size": 6199201999,
        "parameter_size": "3B",
        "family": "deepseek-ocr",
        "vision": true
      }
    ]
  }
  ```

### 2. POST `../ollama/chat` (Structured Output 테스트 챗 수행)
- **설명**: 단일 모델에 대해 지정된 설정(프롬프트, 온도, 포맷 등)에 맞춰 구조화 추론을 요청하고 메트릭 정보를 수집합니다.
- **Request Body (JSON)**:
  ```json
  {
    "model": "gemma3:4b",
    "prompt": "내일 날씨에 맞춰 준비할 옷 세 가지를 알려줘",
    "system": "제공된 JSON Schema 형식에 맞는 JSON만 반환하세요.",
    "temperature": 0.0,
    "format": {
      "type": "object",
      "properties": {
        "items": {
          "type": "array",
          "items": { "type": "string" }
        }
      },
      "required": ["items"],
      "additionalProperties": false
    }
  }
  ```
- **Response Body (JSON)**:
  ```json
  {
    "success": true,
    "model": "gemma3:4b",
    "content": "{\n  \"items\": [\"우산\", \"가벼운 외투\", \"선글라스\"]\n}",
    "metrics": {
      "total_duration_ms": 1250.4,
      "load_duration_ms": 12.1,
      "eval_duration_ms": 980.5,
      "prompt_eval_count": 42,
      "eval_count": 28,
      "tokens_per_second": 28.6
    }
  }
  ```

---

## [CLIENT_COMPONENTS_SPECIFICATION]

### 1. `OllamaTestApp` 상태 관리 객체 (JS)
- **`models`**: 설치된 모델의 로컬 캐시 배열
- **`activeBatchId`**: 현재 실행 중인 벤치마크 배치 세션 식별자
- **`running`**: 전체 테스트 루프의 실행 중 여부 상태 (Boolean)

### 2. `SchemaValidator` (자체 검증 헬퍼)
- **설명**: 외부 대형 라이브러리 의존성 없이, 클라이언트 단에서 파싱된 JSON 객체가 주어진 JSON Schema 사양을 충족하는지 가볍게 분석해 주는 기능입니다.
- **검증 로직**:
  1. JSON 텍스트가 올바른 JSON 포맷인지 파싱 시도 (실패 시 즉시 파싱 오류 마크).
  2. 스키마의 `required` 배열을 읽어, 파싱된 결과의 최상위 레벨에 해당 key가 모두 존재하는지 대조.
  3. 스키마에 정의된 각 속성의 `type`과 실제 값의 자료형(String, Number, Array, Object 등)을 대조하여 매치 여부 판별.
  4. 검증 결과에 따라 요약 테이블에 "일치(성공)", "속성 누락/타입 불일치(경고)", "파싱 실패(에러)" 상태로 출력.

---

## [REVIEW_LOG]
* **검토자**: Reviewer Persona
* **검토 의견**:
  - **API 정밀도 및 격리 전략 비판**:
    1. 사용자가 여러 모델을 돌릴 때, 중간에 브라우저를 닫거나 탭을 이탈하는 경우 백엔드에 걸린 무거운 추론 프로세스들을 취약하게 정지시키지 못하고 계속 서버 메모리를 잡아먹는 병목 현상이 발생할 수 있습니다. 이를 예방하기 위해, 각 순차 요청 시 자바스크립트의 `AbortController`를 생성하여 사용자가 실행 도중 "취소" 또는 "강제 정지" 버튼을 누르거나 페이지를 이탈할 때 클라이언트 요청을 취소(Abort)할 수 있는 설계가 가미되어야 합니다.
    2. 로컬 브라우저 세션에 JSON Schema 템플릿과 프롬프트 상태를 저장하기 위해 `localStorage` 캐싱을 도입하면 페이지가 리로드되거나 다시 방문했을 때 작성 중이던 복잡한 JSON Schema가 날아가는 비극을 방지할 수 있습니다.
