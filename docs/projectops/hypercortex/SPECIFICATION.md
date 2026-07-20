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

---

## [OLLAMA_ADMIN_AND_CONTROL_SPECIFICATION]

Ollama 데몬 생사 감지, VRAM 언로드 및 실시간 로그 스트리밍을 지원하는 백엔드 신규 REST API 규격서입니다.

### 1. GET `/ollama/status`
- **설명**: 로컬 Ollama 데몬 구동 상태 및 VRAM에 현재 적재되어 있는 실시간 활성 모델 목록을 조회합니다.
- **Response Body (JSON - 구동 중 상태)**:
  ```json
  {
    "success": true,
    "running": true,
    "loaded_models": [
      {
        "model": "gemma3:4b",
        "size": 3338801718,
        "expires_at": "2026-07-20T12:05:00Z"
      }
    ]
  }
  ```
- **Response Body (JSON - 정지/크래시 상태)**:
  ```json
  {
    "success": true,
    "running": false,
    "loaded_models": []
  }
  ```

### 2. POST `/ollama/control/<action>`
- **설명**: Ollama 서비스 데몬 시작, 중지, 재시작 및 VRAM 강제 청소(Unload) 명령을 가동합니다.
- **URI Parameter**: `action` = `start` | `stop` | `restart` | `unload`
- **Request Body (unload 액션 시 선택)**:
  ```json
  {
    "model": "gemma3:4b"  // 특정 모델만 선택 해제, 생략 시 VRAM 내 모든 모델 일괄 Unload
  }
  ```
- **Response Body (JSON)**:
  ```json
  {
    "success": true,
    "summary": "Ollama 서비스 재시작 완료"
  }
  ```

### 3. GET `/ollama/logs`
- **설명**: 윈도우즈 OS 내부 `server.log` 최근 200줄의 구동 로그 및 에러 내역을 스트리밍 조회합니다.
- **Query Parameter**: `lines` = 기본 200 (최대 500)
- **Response Body (JSON)**:
  ```json
  {
    "success": true,
    "exists": true,
    "log_file": "C:\\Users\\USER\\.ollama\\logs\\server.log",
    "logs": [
      "[2026-07-20 12:00:00] [info] [system] starting ollama...",
      "[2026-07-20 12:01:25] [info] [compute] load model gemma3:4b onto GPU"
    ]
  }
  ```

---

## [WINDOWS_PROCESS_CONTROL_FALLBACK_SPECIFICATION]

윈도우즈 서비스 계정 권한 거부(Access Denied) 및 프로세스 먹통(Hang) 상태를 무조건 소생시키기 위한 2중 명령 래퍼 설계입니다.

### 1. Ollama 데몬 재시작 (Restart) 시퀀스 (파이썬 내부 명령)
1. 윈도우 서비스 관리 도우미를 우선 구동합니다:
   `PowerShell.exe -Command "Restart-Service -Name Ollama"`
2. 위 서비스 제어가 실패(Exit Code != 0)할 경우, 즉각 태스크킬 강제 프로세스 종료 방식으로 자동 폴백합니다:
   `taskkill /F /IM ollama.exe` (모든 좀비 프로세스까지 완벽하게 강제 소멸)
3. 프로세스 소멸 확인 후, 백그라운드 오프라인 백서 데몬(`ollama serve`) 프로세스를 일반 유저 권한으로 안전 재기동합니다:
   `subprocess.Popen(["ollama", "serve"], creationflags=subprocess.CREATE_NO_WINDOW)` (콘솔창 노출 없이 백그라운드 기동 보증)

### 2. Ollama 윈도우 Logs (`server.log`) 감지 시퀀스
백엔드 기동 즉시 다음 3곳의 고정 경로를 스캔하여 최초로 발굴된 물리 로그 주소를 `OllamaService`의 고정 파일명으로 자동 캐시 바인딩 처리합니다:
1. `f"C:\\Users\\{USERNAME}\\.ollama\\logs\\server.log"` (런타임에 `os.getlogin()` 이나 `os.environ`으로부터 사용자명 동적 획득)
2. `f"C:\\Users\\{USERNAME}\\AppData\\Local\\Ollama\\server.log"`
3. `"C:\\Windows\\System32\\config\\systemprofile\\.ollama\\logs\\server.log"` (윈도우 서비스 기동 시의 격리 시스템 권한용 경로)

---

## [REVIEW_LOG]
* **검토자**: Reviewer Persona
* **검토 의견**:
  - **Ollama API 버전 사양**: `loaded_models` 조회 API (`GET /api/ps`)는 Ollama 0.1.41 버전 이상에서만 제공됩니다. 만약 운영 중인 Ollama 엔진 버전이 이보다 하위 구버전인 경우 API 호출 시 404가 발생합니다. 이 경우, `loaded_models` 조회가 404를 반환하면 백엔드 단에서 예외로 뻗지 않고 그냥 `loaded_models: []` 와 `running: true` 를 유연하게 복원하도록 에러 복원 설계를 마감해 두어야 안전합니다.
  - **인코딩 가드**: 윈도우즈 로그 파일인 `server.log`를 파이썬의 `open(path, 'r')` 로 열어 읽어올 때, 윈도우 특유의 멀티바이트나 특정 특수문자가 섞여 있을 경우 `UnicodeDecodeError`가 발생해 로그 조회가 터질 우려가 다분합니다. (실제 팰월드 로그 분석 로그에서도 cp949 에러 흔적이 식별되었습니다.) 이를 완벽 차단하기 위해 반드시 **`open(path, 'r', encoding='utf-8', errors='ignore')`** 로 감싸서 열어 읽어야 치명 오류를 완벽하게 면제할 수 있습니다.
