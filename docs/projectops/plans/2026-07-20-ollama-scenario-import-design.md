# 2026-07-20 Ollama 테스트 시나리오 가져오기/내보내기 기능 개발 설계서

## [PROBLEM] 요구사항 분석
- **현상**: 사용자가 Ollama Structured Output 테스트를 수행할 때마다 `temperature`, `format`, `system_prompt`, `user_prompt`, `schema_input` 등을 매번 각각 복사하여 입력하거나 수동으로 선택해야 하므로 반복적인 번거로움과 시간 지연이 발생함.
- **요구사항**:
  - AI(Claude, ChatGPT 등)가 기획한 단일 구조화된 JSON 시나리오 파일(또는 텍스트)을 원클릭으로 통째로 붙여넣고 화면 양식에 자동 파싱 분배해 입력해 주는 "가져오기(Import)" 기능 구현.
  - 현재 구성해 둔 입력 양식들을 그대로 JSON 형태로 출력받아 복사 및 아카이빙할 수 있는 "내보내기(Export)" 기능 구현.
  - AI 에이전트에게 보내어 정확한 형식의 시나리오 JSON을 유도해 내는 "AI 프롬프트 가이드라인"을 모달 내에서 상시 확인하고 간편 복사하는 도구 구현.
  - 가져온 시나리오의 직관적인 식별을 위한 "시나리오명 동적 배지(Badge)" 영역 제공.

## [DESIGN] 기술 설계 및 UI/UX 스펙

### 1. 시나리오 JSON 데이터 모델 규격
```json
{
  "title": "시나리오 제목",
  "temperature": 0.2,
  "format": "schema", // none, json, schema 중 택 1
  "system_prompt": "시스템 역할 정의",
  "user_prompt": "유저 입력 텍스트",
  "schema": {
    "type": "object",
    "required": ["필수속성"],
    "properties": {
      "속성": { "type": "string" }
    }
  }
}
```

### 2. UI 레이아웃 설계 (DaisyUI v5 / Tailwind CSS v4)
- **요청 구성 카드 헤더 우측**: `AI 시나리오 설계` 버튼 추가 (모달 오픈용)
- **요청 구성 헤더 영역**: `active-scenario-badge` 상태 배지 동적 노출 영역 추가
- **scenario-modal (dialog)**: 탭 컴포넌트(`tabs-lifted`)를 활용한 2개 탭 구성
  - **탭 1 (AI 프롬프트 가이드)**: 원클릭 복사 전용 가이드라인 텍스트 및 복사 버튼
  - **탭 2 (JSON 가져오기/내보내기)**: JSON 텍스트 에어리어, 가져오기(적용), 현재 설정 내보내기 버튼

### 3. JS 연동 로직 설계 (`ollama-test.js`)
- `initScenarioModal()` 함수 정의: 모달 초기 바인딩, 프롬프트 가이드 설정, 이벤트 리스너(복사, 적용, 내보내기) 등록.
- `applyScenarioJson()` 함수 정의:
  - 입력 JSON에서 마크다운 백틱 코드 블록(```json ... ```) 제거.
  - JSON 구문 문법 오류(syntax) 및 무결성(필수 속성 존재 여부) 체크.
  - `setFormatMode()` 및 개별 폼 입력 바인딩 기동.
  - 시나리오 제목 배지 활성화, `saveState()` 호출을 통한 로컬 저장소 동기화.
  - 모달 닫기 및 성공 토스트 얼럿 출력.
- `exportCurrentToScenarioJson()` 함수 정의: 현재 화면 폼의 실시간 상태를 데이터 규격에 맞게 JSON화하여 가져오기용 텍스트 에어리어에 렌더링.

---

## [REVIEW_LOG] 리뷰어 검토 피드백
- **지적 사항**: 사용자가 외부 AI로부터 마크다운 백틱 코드 펜스(` ```json `)가 감싸진 채로 결과를 복사해 올 가능성이 아주 큼. 이를 단순 `JSON.parse` 하면 크래시가 나므로 전처리 필터링이 필히 요구됨.
- **조치 사항**: JS 파싱 로직 맨 처음에 `cleanJson = cleanJson.replace(/^```json\s*/, '').replace(/```$/, '').trim();` 와 같이 마크다운 코드를 안전하게 정화(sanitize)하고 정규화하는 예외 처리를 선제 반영함.
