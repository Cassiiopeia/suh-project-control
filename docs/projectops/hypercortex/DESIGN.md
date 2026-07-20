# DESIGN

## [ALTERNATIVES_CONSIDERED]

### 대안 A: 완료 후 통째로 덮어쓰기하는 벌크 저장 방식
- **장점**: 단순하고 깔끔한 API 단일 호출로 종료됨.
- **단점**: 중간에 실패하거나 Abort된 항목들을 원천 추적할 수 없어 "과거 이력 기반 실패 모델 재실행"이라는 정교한 핵심 기능을 구현하기 불가능함.

### 대안 B: [선택안] 세션 마스터 선생성 + 개별 모델 결과 비동기 UPSERT 기법 (Stateful & Context-Bound)
- **장점**:
  1. 벤치마크 기동 즉시 `batch_id`를 확보하여, 각 모델 결과가 나오는 즉시 DB에 개별 갱신되므로 실시간 정합성이 100% 보증됨.
  2. `UNIQUE(batch_id, model_name) ON CONFLICT DO UPDATE` (UPSERT) 문법을 도입해 중복 적재를 차단하고 재시도 시 완벽하게 레코드 정보를 업데이트함.
  3. 과거 아코디언 펼침 시 해당 마스터 세션에 보존되어 있던 프롬프트/스키마 컨텍스트를 스레드 클로저 형태로 정확히 바인딩하여 재실행하므로, 과거 이력 위에서도 안전하게 재시도를 성공시키고 이력을 최신화할 수 있음.
- **단점**: 실시간 REST API 호출 수가 늘어나고, 프론트엔드 내 상태 추적 이벤트 바인딩 설계 공수가 다소 증가함.

---

## [SOLUTION]

### 1. 관계형 데이터베이스(RDB) 스키마 상세 설계 (PostgreSQL)
- **`benchmark_batch` (마스터 테이블)**:
  - 실험 일시, 프롬프트, 온도를 기록합니다. `schema_definition`은 스키마 템플릿 정보를 담기 위해 `TEXT` 타입으로 구성합니다.
- **`benchmark_result` (지표 결과 테이블)**:
  - 모델별 개별 실행 성능을 기록합니다.
  - 정합성 수호를 위해 **`CONSTRAINT unique_batch_model UNIQUE (batch_id, model_name)`** 제약을 명시합니다.

### 2. 백엔드 REST API 인터페이스 설계 (`suh-ai-server/flask/router/ollama_router.py` 추가 예정)
- **`POST /ollama/benchmark/batch`** (마스터 생성)
  - *Payload*: `{ prompt, system, temperature, format_mode, schema_definition }`
  - *Response*: `{ success: true, batch_id: N }`
- **`POST /ollama/benchmark/result`** (결과 UPSERT)
  - *Payload*: `{ batch_id, model_name, status, response_content, metrics, schema_compliance }`
  - *Response*: `{ success: true }`
- **`GET /ollama/benchmark/history`** (마스터 목록 조회 - Lazy Loading 대비)
  - *Response*: `{ success: true, batches: [...] }`
- **`GET /ollama/benchmark/history/<batch_id>`** (특정 배치 세부 지표 및 JSON 조회)
  - *Response*: `{ success: true, results: [...] }`

### 3. 프론트엔드 상태 전이 및 Context-Binding 설계 (`ollama-test.js`)
- **실패 모델 재실행 (Retry) 흐름**:
  1. 요약 테이블 렌더링 시, `실패` 배지 우측에 재시도 버튼(`<button class="btn-retry" data-model="모델명">`)을 동적 추가 바인딩합니다.
  2. 사용자가 클릭 시, 해당 배치 카드가 생성될 당시 보존된 `prompt`, `system`, `temperature`, `schema` 데이터를 메모리 클로저 혹은 엘리먼트 `data-*` 속성으로부터 그대로 파싱 추출합니다. (현재 화면 입력창 값으로 오염되는 것을 차단)
  3. 해당 모델 단일 대상을 향해 `runSingleModelBenchmark(batchId, model, config)`를 호출하고 비동기로 결과를 받아옵니다.
  4. 결과를 수신하면 해당 테이블의 Row와 상세 카드를 즉석 갱신하고, `POST /ollama/benchmark/result` 를 호출해 원격 DB 정보를 무결하게 동기화합니다.
- **과거 이력 Lazy-Loading 아코디언 뷰**:
  1. 페이지 진입 시 `GET /ollama/benchmark/history` 를 비동기 호출해 마스터 목록만 가볍게 조회한 뒤, 하단의 이력 영역에 렌더링합니다.
  2. 사용자가 특정 이력 카드의 아코디언(`details` 또는 커스텀 토글)을 **최초로 클릭해 펼치는 순간(On Expand)**, 해당 카드의 세부 지표가 로딩되지 않았음을 인지하고 즉각 `GET /ollama/benchmark/history/<batch_id>`를 호출하여 세부 모델 결과들을 긁어옵니다.
  3. 로드된 결과들을 바탕으로, 실시간 테스트 때와 100% 동일한 요약 테이블 및 상세 결과 카드 레이아웃을 과거 이력 카드 내부에 그대로 예쁘게 복원 조립합니다.
  4. 과거 이력에도 실패 모델이 남아 있다면, 복원된 테이블에서도 위의 재시도 흐름을 완벽히 연쇄 가동시킵니다.

---

## [REVIEW_LOG]
* **검토자**: Reviewer Persona
* **검토 의견**:
  - **디자인 결함 피드백 (과거 이력 복원 후 다운로드)**: 과거 테스트 이력 아코디언을 로드하고 테이블을 복원한 후에도 "보고서 내보내기" 버튼(클립보드 복사, 마크다운 다운로드)이 정상적으로 작동해야 합니다. 이를 위해, 동적으로 생성되는 모든 요약 정보 긁어오기 함수(`generateBatchMarkdownReport`)는 현재 활성 상태의 에디터뿐만 아니라, **해당 배치 카드가 영구 보존하고 있는 스펙 속성들(과거 보존된 프롬프트와 온도, 스키마 등)을 기준으로 마크다운을 빌드하도록** 설계되어야 완벽하게 정밀합니다. 이 결함을 미연에 통제하기 위해 데이터 속성을 카드 엘리먼트에 영구 저장해 두겠습니다.
  - **트랜잭션 차단 방지 (Fail-Open)**: 데이터베이스 인스턴스 지연이나 일시적 다운이 발생해도, 벤치마크 테스트 자체는 브라우저 단에서 멈춤 없이 계속 흘러갈 수 있도록 백엔드 DB 에러 발생 시 예외를 조용히 꿀꺽 흡수(Fail-Open)하고, 프론트에는 성공 마크를 주되 경고를 남기는 우아한 방어 코드를 Flask 레벨에서 처리해 주어야 합니다.
