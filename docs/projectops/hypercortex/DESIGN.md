# DESIGN

## [ALTERNATIVES_CONSIDERED]

### 대안 A: 더블 소형 아이콘 버튼 방식 (선택안)
- **장점**: 
  - 복사(`copy`)와 물리 다운로드(`download`) 동작이 단 1회의 클릭으로 바로 기동되어 UI 낭비가 전혀 없고 작동 속도가 가장 뛰어남.
  - DaisyUI의 `btn-ghost btn-xs` 규격과 Lucide 아이콘을 결합하여 카드 우측 상단에 소형으로 미려하게 밀착 배치함으로써 컴팩트한 레이아웃 유지 가능.
- **단점**: 모바일 혹은 극도로 좁은 뷰포트에서 아이콘 2개가 터치 타깃으로 다소 작게 느껴질 수 있음 (아이콘 사이에 적절한 padding/margin 보장으로 상쇄 가능).

### 대안 B: 다운로드/복사 드롭다운 메뉴 방식
- **장점**: 카드 헤더 영역의 공간을 가장 적게 차지함.
- **단점**: 메뉴 클릭 후 하위 항목을 다시 클릭해야 하는 번거로움(2-click)이 수반되어 벤치마크 결과를 신속히 다중 분석하려는 사용자의 인지 피로를 증가시킴.

---

## [SOLUTION]

### 1. UI/UX 레이아웃 설계 (`ollama-test.html` 및 `ollama-test.js`)
동적으로 생성되는 각 배치 컨테이너 헤더 영역의 구조를 보완합니다.
- **배치 헤더 우측 조작 제어부**:
  ```html
  <div class="flex items-center gap-1.5 shrink-0">
    <!-- 1. 클립보드 복사 버튼 (아이콘: copy) -->
    <button class="btn btn-ghost btn-xs text-primary btn-export-copy" title="AI 보고서 클립보드 복사" data-batch-id="{batchId}">
      <i data-lucide="copy" class="size-3.5"></i>
    </button>
    <!-- 2. 마크다운 다운로드 버튼 (아이콘: download) -->
    <button class="btn btn-ghost btn-xs text-primary btn-export-download" title="마크다운 파일 다운로드" data-batch-id="{batchId}">
      <i data-lucide="download" class="size-3.5"></i>
    </button>
    <!-- 기존 포맷 방식 표시 배지 -->
    <span class="badge badge-primary badge-outline text-xs">{modeLabel}</span>
  </div>
  ```

### 2. 보고서 변환 템플릿 설계 (`ollama-test.js`)
AI와 사람 모두가 완벽하게 정량/정성 평가를 내릴 수 있도록 마크다운 문서를 정밀하게 조립합니다.
- **수집 대상 데이터**:
  - 배치 ID 및 일시
  - 테스트 프롬프트, 시스템 프롬프트, 온도 및 포맷 모드
  - 배치 내부 요약 테이블의 모든 행(Row) 정보 (모델명, 상태, 총 시간, 로드 시간, 생성 시간, 입력/출력 토큰, 추론 속도, 스키마 준수 여부)
  - 각 모델의 들여쓰기된 JSON 응답 텍스트 원문 전체

### 3. 클립보드 복사 보안 컨텍스트 가드 및 예외 처리
- `navigator.clipboard` 실패 또는 비보안(HTTP) IP 환경에서의 오류 차단을 위해 임시 `<textarea>` 요소를 도큐먼트에 동적으로 생성하여 강제 포커싱 후 `document.execCommand('copy')`를 수행하는 견고한 폴백(Fallback) 함수를 바인딩합니다.
- 복사 성공 시 "복사되었습니다!" 토스트 메시지를 화면에 시각적으로 정밀하게 알려줍니다.

### 4. 개발 가이드라인 수칙 명문화 (`CLAUDE.md`)
- **[규칙 1] `apiFetch` 사용 의무화**: 프론트엔드 비동기 요청 코드를 설계할 때는 `X-API-Key` 유실을 차단하기 위해 무조건 `apiFetch` 래퍼만을 사용하도록 규칙을 명시합니다.
- **[규칙 2] `develop` 브랜치 기준 수정 및 개발**: 모든 신규 기능 코딩, 리팩토링, 긴급 패치 작업은 반드시 `develop` 브랜치에서 수행하고, 최종 테스트 통과 후 버전 릴리스 절차를 밟도록 수칙을 고정합니다.

---

## [REVIEW_LOG]
* **검토자**: Reviewer Persona
* **검토 의견**:
  - **디자인 결함 피드백**: 다운로드되는 마크다운 파일의 제목에 한글 및 영문 공백이 들어가면 브라우저 환경에 따라 다운로드 URI 인코딩에 에러를 줄 수 있습니다. 파일명 생성 시 공백을 언더스코어(`_`)로 치환하고, 파일명 포맷을 `ollama_benchmark_batch_X_YYYYMMDD_HHmmss.md` 와 같은 형태로 구성하여 타임스탬프 기반 격리성을 높이는 설계가 안전합니다.
  - **데이터 싱크 정합성**: 복사 및 다운로드 실행 시, 정량 데이터 테이블의 행에서 실시간 렌더링된 최신 텍스트 값을 동적으로 긁어오도록 조립해야 사용자가 눈으로 보고 있는 비교 결과와 내보내지는 문서 내용이 100% 한 치의 오차 없이 일치하게 됩니다.
