# SPECIFICATION

## [FRONTEND_JS_SPECIFICATION]

공통 자바스크립트 파일(`suh-ai-server/flask/static/js/admin-common.js`)에 탑재될 모델 메타분석 및 실시간 다차원 필터링 함수 규격서입니다.

### 1. `window.getActualFamily(m)`
- **설명**: 모델 객체를 분석하여 허깅페이스 경로가 포함되더라도 원천 설계를 파악해 고유의 패밀리명을 문자열로 리턴합니다.
- **매핑 정규식**:
  - `gemma3n`: `/gemma3n/`
  - `gemma3`: `/gemma3|gemma-3/`
  - `gemma4`: `/gemma4|gemma-4/`
  - `deepseek-ocr`: `/deepseek-ocr/`
  - `deepseek-r1`: `/deepseek-r1|deepseek-r-1/`
  - `glm-ocr`: `/glm-ocr|glmocr/`
  - `granite4`: `/granite4|granite-4/`
  - `lfm2.5-thinking`: `/lfm2.5-thinking|lfm-2.5-thinking/`
  - `minicpm-v4.6`: `/minicpm-v4.6|minicpmv4.6/`
  - `ministral-3`: `/ministral-3|ministral3/`
  - `qwen3-embedding`: `/qwen3-embedding|qwen-3-embedding/`
  - `qwen3-vl`: `/qwen3-vl|qwen-3-vl/`
  - `qwen3.5`: `/qwen3.5|qwen-3.5/`
  - `qwen3`: `/qwen3|qwen-3/`
  - `hyperclovax`: `/hyperclovax|hyper-clova/`
  - `kanana`: `/kanana/`
  - `llava`: `/llava/`
- **리턴**: 정제된 영문 소문자 패밀리명 (일치 키워드가 없을 경우 백엔드의 `m.family` 또는 단수 소문자 명칭 리턴)

### 2. `window.parseParameterSize(paramStr)`
- **설명**: 문자열 기반의 파라미터 규격을 실수 수치로 파싱하여 연산이 가능하도록 만듭니다.
- **사양**:
  - `4.3B` ➡️ `4.3` (실수형 리턴)
  - `270M` ➡️ `0.27` (`270 / 1000` 처리)
  - 비어있거나 무효하면 `0` 리턴

### 3. `window.filterModelList(models, filters)`
- **설명**: 설치된 전체 모델 데이터셋에 대해 다차원 동시성 필터 파이프라인을 작동하여 최종 통과된 배열을 반환합니다.
- **파라미터 규격**:
  ```json
  {
    "query": "gemma",
    "params": "all" | "under_1b" | "1b_4b" | "4b_8b" | "over_8b",
    "maxSizeStep": 0 | 1 | 2 | 3 | 4 | 5 | 6,
    "capability": "all" | "vision" | "embedding" | "text",
    "source": "all" | "ollama" | "hf"
  }
  ```
- **슬라이더 용량 단계 매핑 (상한 기가바이트)**:
  - `0`: 0.5GB 이하 (`<= 0.5 * 1024 * 1024 * 1024` bytes)
  - `1`: 1.0GB 이하 (`<= 1.0 * 1024 * 1024 * 1024` bytes)
  - `2`: 4.0GB 이하 (`<= 4.0 * 1024 * 1024 * 1024` bytes)
  - `3`: 8.0GB 이하 (`<= 8.0 * 1024 * 1024 * 1024` bytes)
  - `4`: 12.0GB 이하 (`<= 12.0 * 1024 * 1024 * 1024` bytes)
  - `5`: 16.0GB 이하 (`<= 16.0 * 1024 * 1024 * 1024` bytes)
  - `6`: 전체 (제한 해제)

---

## [DATA_FLOW_SPECIFICATION]

다음은 브라우저에서 모델 데이터가 로드되고 필터바 조작 이벤트에 따라 다차원 분석 필터링이 수행되어 뷰가 업데이트되는 전체 시퀀스 및 데이터 흐름을 도식화한 다이어그램입니다.

```
+--------------------------------------------+
|        Backend GET /models/installed       |
+---------------------+----------------------+
                      |
                      | [Raw Installed Models JSON Array]
                      ▼
+---------------------+----------------------+
|             window.apiFetch()              |
+---------------------+----------------------+
                      |
                      ▼
+---------------------+----------------------+
|            getActualFamily(m)              | <--- hf.co/ 및 일반 모델 아키텍처 정밀 복원
+---------------------+----------------------+
                      |
                      ▼
+---------------------+----------------------+
|       DOM Event: Filter Changed (Debounced) | <--- 텍스트, 파라미터, 용량 슬라이더, 유형, 출처
+---------------------+----------------------+
                      |
                      ▼
+---------------------+----------------------+
|         window.filterModelList()           |
|  - Query Filter (대소문자 무시)               |
|  - Parameter Limit (parseParameterSize)    |
|  - File Capacity Limit (Stepped range)     |
|  - Capability Tag Match (vision/embed/text)|
|  - Download Source Match (ollama vs hf)    |
+---------------------+----------------------+
                      |
                      | [Filtered Models Subset Array]
                      ▼
+---------------------+----------------------+
|            renderFilteredUI()              |
|  - Grouping by getActualFamily(m)          |
|  - Hide empty family heading rows/cards    |
|  - Keep checkbox check state independent   | <--- Ollama 테스트 페이지용 체크 상태 변수 보존
+--------------------------------------------+
```

---

## [REVIEW_LOG]
* **검토자**: Reviewer Persona (Devil's Advocate)
* **검토 의견**:
  - **API 독립성 및 무상태성 검증**: 이 기능은 전적으로 클라이언트 사이드의 메모리 연산으로 완성되므로 백엔드 DB 트랜잭션이나 API 추가 개발 리스크가 '0'에 수렴하는 극도로 격리되고 안전한 아키텍처 사양입니다.
  - **슬라이더 입력 정밀도 제안**: range input 조작 시 실시간으로 바뀐 제한 기가바이트(예: "4.0GB 이하") 텍스트가 눈금 바로 위나 옆에 동적 뱃지(`<span class="badge">`) 형태로 즉시 표시되어야 드래그하는 손맛과 시각적 피드백이 우아해집니다. 이 동적 텍스트 바인딩 헬퍼를 JS 필터 변경 핸들러에 필수로 추가하는 마크업 세부 스펙 수립을 권고합니다.
