### 문제 요약
관리자 페이지 내 카드 및 콘텐츠 영역의 가로 너비가 화면 크기를 늘려도 반응형으로 확장되지 않고 고정되어 답답하게 보이는 현상 | **타입**: Flask / Tailwind CSS | **환경**: Chrome / Edge 등 데스크톱 웹 브라우저

### 원인 분석
**근본 원인**: `admin/ollama-test.html` 및 기타 템플릿 파일들의 메인 컨테이너 태그에 Tailwind CSS의 `max-w-5xl` (최대 너비 1024px) 또는 `max-w-6xl` (최대 너비 1152px) 클래스가 강제로 지정되어 있습니다.
**발생 메커니즘**: 
1. 각 템플릿 파일 상단에는 다음과 같은 컨테이너 div가 선언되어 있습니다.
   - `admin/ollama-test.html`: `<div class="space-y-6 max-w-5xl mx-auto">`
   - `admin/dashboard.html`: `<div class="space-y-6 max-w-5xl mx-auto">`
   - `admin/palworld.html`: `<div class="space-y-6 max-w-5xl mx-auto">`
   - `admin/logs.html`: `<div class="card bg-base-100 shadow max-w-5xl mx-auto">`
   - `admin/models.html`: `<div class="space-y-6 max-w-6xl mx-auto">`
   - `admin/tts.html`: `<div class="space-y-6 max-w-6xl mx-auto">`
   - `admin/audit.html`: `<div class="card bg-base-100 shadow max-w-6xl mx-auto">`
2. 이 `max-w-5xl`(1024px) 및 `max-w-6xl`(1152px) 클래스로 인해 화면을 아무리 늘려도 해당 영역을 초과해 커지지 않습니다. 특히 모델 다중 선택 영역(`model-checkbox-list`), JSON Schema 입력 창, 벤치마크 결과 비교 목록 등 가로 너비가 넓을수록 정보를 한눈에 파악하기 좋은 페이지에서 심각한 가시성 제약이 발생합니다.

---

### 해결 방법

#### Quick Fix (특정 화면만 변경)
가장 너비 제약이 심한 `ollama-test.html` 화면만 `max-w-none` 또는 넓은 반응형 너비(`max-w-[1400px]` 혹은 `max-w-7xl` 등)로 개별 패치합니다.

```html
<!-- suh-ai-server/flask/templates/admin/ollama-test.html 수정 전 -->
<div class="space-y-6 max-w-5xl mx-auto">

<!-- suh-ai-server/flask/templates/admin/ollama-test.html 수정 후 (예: 1400px로 넉넉하게 지정) -->
<div class="space-y-6 max-w-[1400px] mx-auto">
```

#### Root Fix (전체 탭 최적화 - 권장)
데스크톱 관리자 콘솔 특성상, 정보량이 많은 페이지(Ollama 테스트, 모델 관리, TTS 관리, 감사로그 등)는 와이드 모니터의 장점을 극대화할 수 있도록 컨테이너의 제한 너비를 전체적으로 상향(`max-w-7xl`인 1280px 또는 `max-w-[1440px]`, 혹은 완전 100% 꽉 채우는 `max-w-none`) 조정하는 것이 근본적인 해결책입니다.

1. **Ollama 테스트** (`admin/ollama-test.html`): 다중 모델 선택 체크박스, JSON Schema 입력란, 다중 결과 카드 비교를 위해 넉넉한 너비가 필요하므로 `max-w-none` (가로 전체 채움, 기본 padding 유지) 또는 `max-w-[1440px]` 수준으로 상향합니다.
2. **나머지 로그 및 관리 화면**: 필요에 맞춰 `max-w-7xl` 이상으로 조정합니다.

---

### 검증
1. `ollama-test.html` 파일의 최상단 div 클래스를 `max-w-[1440px] mx-auto` 또는 `max-w-none`으로 수정합니다.
2. 브라우저 화면을 좌우로 크게 확대/축소하여 카드 영역이 최대 너비까지 유연하고 넓게 반응형으로 확장되는지 시각적으로 확인합니다.

### 재발 방지
- 관리자용 대시보드 및 복잡한 구성 화면을 설계할 때, 표준 가로 해상도를 제한하는 기본 템플릿 제약(`max-w-5xl`) 대신 화면 특성(테이블, 로그, 차트 배치 등)에 맞춰 적절히 너비 한계를 유연하게 확장하여 반영하도록 기획 및 사양 단계에서 크기 감사를 거칩니다.
