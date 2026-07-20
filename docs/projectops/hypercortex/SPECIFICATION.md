# SPECIFICATION

## [DATABASE_DDL_SPECIFICATION]

PostgreSQL 데이터베이스 마이그레이션을 위한 DDL 사양 정의입니다.
이 SQL은 `suh-ai-server/flask/migrations/0003__create_benchmark_history.sql` 파일로 보관되어 앱 기동 시 yoyo 마이그레이션을 통해 자동 반영됩니다.

```sql
-- 1. 벤치마크 배치 마스터 테이블 생성
CREATE TABLE IF NOT EXISTS benchmark_batch (
    id SERIAL PRIMARY KEY,
    prompt TEXT NOT NULL,
    system_prompt TEXT,
    temperature NUMERIC(3,2) NOT NULL DEFAULT 0.0,
    format_mode VARCHAR(20) NOT NULL,
    schema_definition TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 2. 벤치마크 세부 결과 테이블 생성
CREATE TABLE IF NOT EXISTS benchmark_result (
    id SERIAL PRIMARY KEY,
    batch_id INT NOT NULL,
    model_name VARCHAR(100) NOT NULL,
    status VARCHAR(20) NOT NULL,
    response_content TEXT,
    total_duration_ms NUMERIC(12,2),
    load_duration_ms NUMERIC(12,2),
    eval_duration_ms NUMERIC(12,2),
    prompt_eval_count INT,
    eval_count INT,
    tokens_per_second NUMERIC(6,1),
    schema_compliance VARCHAR(20) NOT NULL DEFAULT 'N/A',
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_batch FOREIGN KEY (batch_id) REFERENCES benchmark_batch(id) ON DELETE CASCADE,
    CONSTRAINT unique_batch_model UNIQUE (batch_id, model_name)
);

-- 3. 조회 최적화를 위한 인덱스 추가
CREATE INDEX IF NOT EXISTS idx_result_batch ON benchmark_result(batch_id);
```

---

## [API_ENDPOINTS_SPECIFICATION]

### 1. POST `/ollama/benchmark/batch`
- **설명**: 벤치마크를 가동할 때 마스터 세션을 최초로 생성합니다.
- **Request Body (JSON)**:
  ```json
  {
    "prompt": "내일 날씨 가방 챙기기",
    "system": "JSON Schema에만 맞게 출력하세요.",
    "temperature": 0.0,
    "format_mode": "schema",
    "schema_definition": "{\"type\": \"object\", ...}"
  }
  ```
- **Response Body (JSON)**:
  ```json
  {
    "success": true,
    "batch_id": 42
  }
  ```

### 2. POST `/ollama/benchmark/result`
- **설명**: 모델 테스트가 끝났을 때 정량/정성 지표를 UPSERT 합니다.
- **Request Body (JSON)**:
  ```json
  {
    "batch_id": 42,
    "model_name": "gemma3:4b",
    "status": "success",
    "response_content": "{\n  \"items\": [\"우산\"]\n}",
    "metrics": {
      "total_duration_ms": 1250.4,
      "load_duration_ms": 12.1,
      "eval_duration_ms": 980.5,
      "prompt_eval_count": 42,
      "eval_count": 28,
      "tokens_per_second": 28.6
    },
    "schema_compliance": "PASS"
  }
  ```
- **Response Body (JSON)**:
  ```json
  {
    "success": true
  }
  ```
- **UPSERT SQL 쿼리 설계**:
  ```sql
  INSERT INTO benchmark_result (
      batch_id, model_name, status, response_content, 
      total_duration_ms, load_duration_ms, eval_duration_ms, 
      prompt_eval_count, eval_count, tokens_per_second, schema_compliance, updated_at
  ) VALUES (
      %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, CURRENT_TIMESTAMP
  ) ON CONFLICT (batch_id, model_name) DO UPDATE SET
      status = EXCLUDED.status,
      response_content = EXCLUDED.response_content,
      total_duration_ms = EXCLUDED.total_duration_ms,
      load_duration_ms = EXCLUDED.load_duration_ms,
      eval_duration_ms = EXCLUDED.eval_duration_ms,
      prompt_eval_count = EXCLUDED.prompt_eval_count,
      eval_count = EXCLUDED.eval_count,
      tokens_per_second = EXCLUDED.tokens_per_second,
      schema_compliance = EXCLUDED.schema_compliance,
      updated_at = CURRENT_TIMESTAMP;
  ```

### 3. GET `/ollama/benchmark/history`
- **설명**: 최근 벤치마크 테스트 마스터 세션 이력을 페이징하여 가져옵니다. (최근 15개 한도)
- **Response Body (JSON)**:
  ```json
  {
    "success": true,
    "batches": [
      {
        "id": 42,
        "prompt": "내일 날씨 가방 챙기기",
        "system_prompt": "JSON Schema에만 맞게 출력하세요.",
        "temperature": 0.0,
        "format_mode": "schema",
        "schema_definition": "{\"type\": \"object\", ...}",
        "created_at": "2026-07-20T12:00:00Z"
      }
    ]
  }
  ```

### 4. GET `/ollama/benchmark/history/<batch_id>`
- **설명**: 특정 배치 ID에 연계된 모든 개별 모델들의 상세 응답 및 지표를 로드합니다. (Lazy Loading 처리 대상)
- **Response Body (JSON)**:
  ```json
  {
    "success": true,
    "results": [
      {
        "model_name": "gemma3:4b",
        "status": "success",
        "response_content": "{\n  \"items\": [\"우산\"]\n}",
        "total_duration_ms": 1250.4,
        "load_duration_ms": 12.1,
        "eval_duration_ms": 980.5,
        "prompt_eval_count": 42,
        "eval_count": 28,
        "tokens_per_second": 28.6,
        "schema_compliance": "PASS",
        "updated_at": "2026-07-20T12:01:25Z"
      }
    ]
  }
  ```

---

## [CLIENT_DATA_BINDING_SPECIFICATION]

과거 이력 테이블 복원 후, 재시도 수행 시 에디터 오염을 방지하기 위해 생성되는 배치 카드 엘리먼트(`div#batch-run-X`) 자체에 당시 세션 정보들을 `dataset` 속성으로 영구 바인딩합니다.

```html
<div class="border border-primary/20 rounded-xl p-4 bg-base-100 shadow" 
     id="batch-run-42"
     data-batch-id="42"
     data-prompt="내일 날씨 가방 챙기기"
     data-system-prompt="JSON Schema에만 맞게 출력하세요."
     data-temperature="0.0"
     data-format-mode="schema"
     data-schema-definition="{\"type\": \"object\", ...}">
  ...
</div>
```

- **클라이언트 자바스크립트 내 추출 및 재실행 흐름**:
  ```javascript
  const card = el('batch-run-42');
  const sessionConfig = {
    prompt: card.dataset.prompt,
    system: card.dataset.systemPrompt,
    temperature: parseFloat(card.dataset.temperature),
    format_mode: card.dataset.formatMode,
    schema: card.dataset.schemaDefinition ? JSON.parse(card.dataset.schemaDefinition) : null
  };
  // 해당 sessionConfig를 그대로 유지하여 해당 실패 모델에 대해서만 chat 재시도 및 UPSERT 기동
  ```

---

## [REVIEW_LOG]
* **검토자**: Reviewer Persona
* **검토 의견**:
  - **API 결합 보안**: 조회 및 백엔드 CRUD API 등록 시 관리자 권한을 체크해야 하며, `/ollama/*` 라우트는 이미 Nginx 및 백엔드 미들웨어에서 `X-API-Key` 헤더를 검증하도록 강구되어 있으므로, 4개의 신규 API 역시 Nginx 프록시 보호막과 동일하게 `@audited` 및 `X-API-Key` 검증 데코레이터를 완벽하게 부착해야 데이터 유출 및 SQL 인젝션 공격 등의 위해 요소를 원천 제거할 수 있습니다.
  - **SQL 인젝션 방어**: 파이썬 측에서 SQL을 작성해 DB에 적재할 때, 문자열 포맷팅(`f"..."`)을 활용한 직접 바인딩을 일체 금지하고, 무조건 안전한 플레이스홀더 파라미터 맵핑 기법(`cur.execute(query, (batch_id, ...))`)만을 의무 활용하여 SQL Injection을 방어하겠습니다.
