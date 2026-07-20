# Ollama Structured Output Benchmark Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ollama Structured Output 테스트 페이지를 여러 모델을 한 번에 다중 선택하여 순차 테스트하고 상세한 입출력 토큰 규모 및 속도를 일목요연하게 상호 대조해볼 수 있는 정교한 벤치마킹 대시보드로 고도화합니다.

**Architecture:** 
- 기존의 단일 선택 드롭다운 UI를 계열(Family)별 체크박스 리스트로 개편합니다.
- 배치 세션(Batch Session) 단위 비동기 순차 루프(`for...of`)를 실행하여 서버 자원 오염을 차단합니다.
- 실행 중간에 중단할 수 있도록 `AbortController`를 구성하고, 결과를 다중 메트릭 테이블 및 포맷팅된 JSON 응답 카드로 상세 시각화합니다.
- `localStorage`에 상태를 보존하여 새로고침 시에도 작업 컨텍스트가 유지되도록 합니다.

**Tech Stack:** HTML5, CSS3, Tailwind CSS, DaisyUI, Vanilla JS (ES6), Flask (Backend Backend API)

## Global Constraints
- 수정 작업은 오직 프론트엔드 파일인 `suh-ai-server/flask/templates/admin/ollama-test.html`과 `suh-ai-server/flask/static/js/ollama-test.js`에 국한하며, 백엔드 라우터 및 서비스는 기존 사양을 최대한 변경 없이 그대로 연계합니다.
- 모든 UI 문구, 주석 및 레이블은 글로벌 룰에 따라 한국어로 표기합니다.
- 비동기 로직 내에서 메모리 회복을 위한 300ms의 안정화 sleep 인터벌을 준수합니다.

---

### Task 1: ollama-test.html UI 마크업 개편

**Files:**
- Modify: `suh-ai-server/flask/templates/admin/ollama-test.html`

**Interfaces:**
- Consumes: 기존 `ollama-test.html` 레이아웃 구조
- Produces: 다중 모델 체크박스 영역, 상태 진행 프로그레스 바, 배치 요약 비교 테이블 섹션이 포함된 풍부한 마크업

- [ ] **Step 1: 마크업 수정 적용**

`suh-ai-server/flask/templates/admin/ollama-test.html` 파일에서 기존 단일 모델 드롭다운 섹션을 패밀리 그룹화 다중 체크박스 및 배치 비교 요약 테이블 영역으로 교체합니다.

```html
<!-- 구버전 단일 모델 select 부분을 아래와 같이 다중 체크박스로 변경 -->
<fieldset class="fieldset w-full">
  <legend class="fieldset-legend">모델 선택 (다중 선택 가능)</legend>
  <div class="flex gap-2 mb-2">
    <button id="model-select-all" class="btn btn-xs btn-outline">전체 선택</button>
    <button id="model-select-none" class="btn btn-xs btn-outline">전체 해제</button>
    <button id="model-refresh" class="btn btn-xs btn-outline" title="모델 목록 새로고침">
      <i data-lucide="refresh-cw" class="size-3"></i>새로고침
    </button>
  </div>
  <div id="model-checkbox-list" class="flex flex-wrap gap-2 border border-base-300 rounded-lg p-3 bg-base-200/50 max-h-60 overflow-y-auto w-full">
    <span class="text-sm opacity-60">설치된 모델을 불러오는 중...</span>
  </div>
</fieldset>

<!-- 실행 버튼 및 진행 인디케이터 구성 변경 -->
<div class="card-actions items-center mt-2">
  <button id="run-btn" class="btn btn-primary btn-sm">
    <i data-lucide="play" class="size-4"></i>실행
  </button>
  <button id="stop-btn" class="btn btn-error btn-sm hidden">
    <i data-lucide="square" class="size-4"></i>중지
  </button>
  <div id="run-progress-container" class="flex items-center gap-3 hidden w-full max-w-md mt-2 md:mt-0">
    <progress id="run-progress" class="progress progress-primary w-40" value="0" max="100"></progress>
    <span id="run-status-text" class="text-sm font-semibold opacity-80">준비 중...</span>
    <span class="text-xs opacity-60">(경과 시간: <span id="run-elapsed">0.0</span>s)</span>
  </div>
</div>
```

- [ ] **Step 2: 수동 확인**
Flask 개발서버를 기동하여 http://localhost/api/flask/admin/ollama-test 페이지를 브라우저에서 열어 수정된 마크업 UI 요소들이 깔끔하게 렌더링되는지 확인합니다.

- [ ] **Step 3: Git Commit**

```bash
git add suh-ai-server/flask/templates/admin/ollama-test.html
git commit -m "feat(ollama-test): 다중 모델 선택 및 진행바 마크업 개편"
```

---

### Task 2: ollama-test.js 모델 그룹 렌더링 및 로컬 세션 캐싱 구현

**Files:**
- Modify: `suh-ai-server/flask/static/js/ollama-test.js`

**Interfaces:**
- Consumes: `GET ../ollama/models` API 응답 데이터
- Produces: 계열별 다중 체크박스 목록 동적 렌더링, `localStorage` 영구 보존 기능

- [ ] **Step 1: 자바스크립트 초기화 및 패밀리 그룹화 기능 교체**

`suh-ai-server/flask/static/js/ollama-test.js`의 최상단 전역 변수 및 모델 로드 로직을 개편합니다.

```javascript
// 기존 변수 유지 및 신규 추가
let formatMode = 'schema';
let running = false;
let resultSeq = 0;
let abortController = null;
let installedModels = []; // 설치 모델 캐시

const HF_FAMILY = 'HuggingFace';

function familyOf(name) {
  if (name.indexOf('hf.co/') === 0) return HF_FAMILY;
  return name.split(':')[0];
}

function groupByFamily(models) {
  const groups = {};
  models.forEach(function (m) {
    const fam = familyOf(m.name);
    (groups[fam] = groups[fam] || []).push(m);
  });
  return Object.keys(groups)
    .sort(function (a, b) {
      if (a === HF_FAMILY) return 1;
      if (b === HF_FAMILY) return -1;
      return a.localeCompare(b);
    })
    .map(function (fam) {
      groups[fam].sort(function (a, b) { return a.name.localeCompare(b.name); });
      return [fam, groups[fam]];
    });
}

function fmtSize(bytes) {
  if (!bytes && bytes !== 0) return '-';
  const gb = bytes / 1024 / 1024 / 1024;
  if (gb >= 1) return gb.toFixed(1) + 'GB';
  return (bytes / 1024 / 1024).toFixed(0) + 'MB';
}

// 모델 다중 체크박스 리스트 그리기
async function loadModels() {
  const container = el('model-checkbox-list');
  try {
    const resp = await apiFetch(OLLAMA_API + '/models');
    const data = await resp.json();
    if (!resp.ok) throw new Error(data.error || '모델 목록 조회 실패');
    installedModels = data.models;
    renderModelCheckboxes();
    restoreState(); // 모델 로딩 완료 후 이전 상태 복원
  } catch (e) {
    container.innerHTML = '<span class="text-error">모델 조회 실패: ' + escapeHtml(e.message) + '</span>';
  }
}

function renderModelCheckboxes() {
  const container = el('model-checkbox-list');
  if (!installedModels.length) {
    container.innerHTML = '<span class="text-sm opacity-60">설치된 모델이 없습니다.</span>';
    return;
  }
  container.innerHTML = groupByFamily(installedModels).map(function (group) {
    const boxes = group[1].map(function (m) {
      const sizeStr = m.size ? ' (' + fmtSize(m.size) + ')' : '';
      const isVision = m.name.includes('vision') || m.name.includes('-vl') || m.name.includes('ocr');
      const visionBadge = isVision ? ' <span class="badge badge-info badge-xs shrink-0">vision</span>' : '';
      return '<label class="label cursor-pointer gap-2 border border-base-300 rounded-lg px-2 py-1 bg-base-100 hover:bg-base-200 transition-colors">'
        + '<input type="checkbox" class="checkbox checkbox-xs model-check" value="' + escapeHtml(m.name) + '">'
        + '<span class="font-mono text-xs break-all">' + escapeHtml(m.name) + sizeStr + '</span>'
        + visionBadge
        + '</label>';
    }).join('');
    return '<div class="w-full">'
      + '<div class="text-xs font-semibold opacity-60 mt-1 mb-1">'
      + escapeHtml(group[0]) + ' <span class="badge badge-ghost badge-xs">' + group[1].length + '</span></div>'
      + '<div class="flex flex-wrap gap-1.5">' + boxes + '</div>'
      + '</div>';
  }).join('');
}
```

- [ ] **Step 2: localStorage 로컬 상태 캐싱 추가**

작성 중이던 프롬프트 및 선택 상태를 영구적으로 저장하고 로딩하는 함수를 구현합니다.

```javascript
function saveState() {
  const selectedModels = Array.from(document.querySelectorAll('.model-check:checked')).map(cb => cb.value);
  const state = {
    selectedModels: selectedModels,
    temperature: el('temperature').value,
    formatMode: formatMode,
    systemPrompt: el('system-prompt').value,
    userPrompt: el('user-prompt').value,
    schemaInput: el('schema-input').value,
  };
  localStorage.setItem('ollama_structured_test_state', JSON.stringify(state));
}

function restoreState() {
  try {
    const raw = localStorage.getItem('ollama_structured_test_state');
    if (!raw) return;
    const state = JSON.parse(raw);
    if (state.selectedModels && Array.isArray(state.selectedModels)) {
      document.querySelectorAll('.model-check').forEach(cb => {
        cb.checked = state.selectedModels.includes(cb.value);
      });
    }
    if (state.temperature != null) el('temperature').value = state.temperature;
    if (state.formatMode != null) setFormatMode(state.formatMode);
    if (state.systemPrompt != null) el('system-prompt').value = state.systemPrompt;
    if (state.userPrompt != null) el('user-prompt').value = state.userPrompt;
    if (state.schemaInput != null) {
      el('schema-input').value = state.schemaInput;
      validateSchema();
    }
  } catch (e) {
    console.error('State restore failed:', e);
  }
}
```

- [ ] **Step 3: 상태 이벤트 리스너 바인딩**

```javascript
// DOMContentLoaded 이벤트 리스너 내부에 등록
el('model-select-all').addEventListener('click', function() {
  document.querySelectorAll('.model-check').forEach(cb => cb.checked = true);
  saveState();
});
el('model-select-none').addEventListener('click', function() {
  document.querySelectorAll('.model-check').forEach(cb => cb.checked = false);
  saveState();
});
el('temperature').addEventListener('input', saveState);
el('system-prompt').addEventListener('input', saveState);
el('user-prompt').addEventListener('input', saveState);
el('schema-input').addEventListener('input', saveState);
document.querySelectorAll('#format-mode [data-mode]').forEach(btn => {
  btn.addEventListener('click', saveState);
});
```

- [ ] **Step 4: Git Commit**

```bash
git add suh-ai-server/flask/static/js/ollama-test.js
git commit -m "feat(ollama-test): 모델 다중 선택 렌더링 및 로컬 상태 영구 보존 적용"
```

---

### Task 3: 비동기 순차 루프 벤치마크 및 중지(Abort) 제어 기능 구현

**Files:**
- Modify: `suh-ai-server/flask/static/js/ollama-test.js`

**Interfaces:**
- Consumes: `POST ../ollama/chat` API
- Produces: 순차 벤치마킹 실행 루프, AbortController에 기반한 도중 취소 제어

- [ ] **Step 1: 비동기 딜레이 및 Abort 기능 추가**

```javascript
const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));

function stopExecution() {
  if (abortController) {
    abortController.abort();
    abortController = null;
    showToast('사용자에 의해 벤치마크가 중지되었습니다.', 'warning');
  }
}

// run 함수 완전 개편
async function run() {
  if (running) return;
  const selectedModels = Array.from(document.querySelectorAll('.model-check:checked')).map(cb => cb.value);
  const prompt = el('user-prompt').value.trim();
  
  if (!selectedModels.length) { showToast('테스트할 모델을 하나 이상 선택하세요.', 'warning'); return; }
  if (!prompt) { showToast('프롬프트를 입력하세요.', 'warning'); return; }
  if (!validateSchema()) return;

  running = true;
  el('run-btn').classList.add('hidden');
  el('stop-btn').classList.remove('hidden');
  el('run-progress-container').classList.remove('hidden');

  abortController = new AbortController();
  const { signal } = abortController;

  const totalModels = selectedModels.length;
  let currentIdx = 0;
  
  const startedAt = performance.now();
  const timer = setInterval(function () {
    el('run-elapsed').textContent = ((performance.now() - startedAt) / 1000).toFixed(1);
  }, 100);

  // 고유 배치 그룹 헤더 카드 추가 (테이블 및 하위 상세 카드를 감쌈)
  const batchId = ++resultSeq;
  const batchWrapper = addBatchContainer(batchId, prompt, formatMode);

  try {
    for (const model of selectedModels) {
      if (signal.aborted) break;
      
      currentIdx++;
      // 진행 바 업데이트
      const percent = Math.round((currentIdx / totalModels) * 100);
      el('run-progress').value = percent;
      el('run-status-text').textContent = model + ' (' + currentIdx + '/' + totalModels + ') 실행 중...';

      // 테이블에 "실행 중..." 행(Row) 추가
      const row = addTablePlaceholderRow(batchId, model);

      const reqBody = {
        model: model,
        prompt: prompt,
        temperature: parseFloat(el('temperature').value) || 0,
      };
      const system = el('system-prompt').value.trim();
      if (system) reqBody.system = system;
      if (formatMode === 'json') reqBody.format = 'json';
      if (formatMode === 'schema') reqBody.format = JSON.parse(el('schema-input').value);

      const modelStart = performance.now();
      try {
        const resp = await fetch(OLLAMA_API + '/chat', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(reqBody),
          signal: signal,
        });
        
        const data = await resp.json();
        if (!resp.ok) throw new Error(data.error || 'HTTP ' + resp.status);

        const durationMs = performance.now() - modelStart;
        // 1. 요약 테이블 갱신
        updateTableSuccessRow(row, model, data.metrics, data.content);
        // 2. 상세 결과 카드 추가
        addDetailCard(batchWrapper, { ok: true, model: model, mode: formatMode, content: data.content, metrics: data.metrics });

      } catch (err) {
        if (err.name === 'AbortError') {
          updateTableFailRow(row, model, '중단됨');
          break;
        }
        updateTableFailRow(row, model, err.message);
        addDetailCard(batchWrapper, { ok: false, model: model, mode: formatMode, error: err.message });
      }

      // 모델 전환 및 언로드 대기를 위한 300ms 안정화 슬립
      await sleep(300);
    }
  } finally {
    clearInterval(timer);
    running = false;
    abortController = null;
    el('run-btn').classList.remove('hidden');
    el('stop-btn').classList.add('hidden');
    el('run-progress-container').classList.add('hidden');
    validateSchema();
  }
}
```

- [ ] **Step 2: 중지 버튼 이벤트 바인딩**

```javascript
// DOMContentLoaded 내부
el('stop-btn').addEventListener('click', stopExecution);
```

- [ ] **Step 3: Git Commit**

```bash
git add suh-ai-server/flask/static/js/ollama-test.js
git commit -m "feat(ollama-test): 비동기 직렬 벤치마크 및 중지 메커니즘 구축"
```

---

### Task 4: 실시간 요약 비교 테이블 및 지표 카드 고도화 렌더링 구현

**Files:**
- Modify: `suh-ai-server/flask/static/js/ollama-test.js`

**Interfaces:**
- Consumes: 백엔드로부터 응답받은 metrics 정보 객체
- Produces: 요약 비교 테이블 동적 주입, 자체 스키마 정밀 검증 렌더링

- [ ] **Step 1: 동적 배치 컨테이너(Batch Container) 레이아웃 생성 구현**

```javascript
// 배치 런 단위의 카드 묶음을 동적으로 헤더와 함께 추가
function addBatchContainer(batchId, prompt, mode) {
  el('result-empty') && el('result-empty').remove();
  
  const container = document.createElement('div');
  container.className = 'border border-primary/20 rounded-xl p-4 bg-base-100 shadow space-y-4';
  container.id = 'batch-run-' + batchId;

  const modeLabel = MODE_LABELS[mode] || mode;
  container.innerHTML = 
    '<div class="flex items-center justify-between border-b border-base-300 pb-2">'
    + '  <div class="space-y-1">'
    + '    <h3 class="font-bold text-sm flex items-center gap-2 text-primary">'
    + '      <i data-lucide="layers" class="size-4"></i>배치 테스트 #' + batchId
    + '    </h3>'
    + '    <div class="text-xs opacity-70 font-mono break-all max-w-2xl">프롬프트: "' + escapeHtml(prompt) + '"</div>'
    + '  </div>'
    + '  <span class="badge badge-primary badge-outline text-xs">' + modeLabel + '</span>'
    + '</div>'
    + '<!-- 배치 요약 테이블 -->'
    + '<div class="overflow-x-auto border border-base-200 rounded-lg">'
    + '  <table class="table table-xs w-full text-center">'
    + '    <thead>'
    + '      <tr>'
    + '        <th class="text-left">모델</th>'
    + '        <th>상태</th>'
    + '        <th>총 시간</th>'
    + '        <th>로드 지연</th>'
    + '        <th>추론 시간</th>'
    + '        <th>인풋 토큰</th>'
    + '        <th>아웃풋 토큰</th>'
    + '        <th>속도 (tok/s)</th>'
    + '        <th>Schema 준수</th>'
    + '      </tr>'
    + '    </thead>'
    + '    <tbody id="batch-table-body-' + batchId + '"></tbody>'
    + '  </table>'
    + '</div>'
    + '<!-- 개별 상세 응답 카드 아코디언/목록 -->'
    + '<div class="grid grid-cols-1 md:grid-cols-2 gap-3" id="batch-details-' + batchId + '"></div>';

  el('result-list').prepend(container);
  el('result-count').textContent = el('result-list').children.length;
  
  // Lucide 아이콘 새로 그리기
  if (typeof lucide !== 'undefined') {
    lucide.createIcons({ attrs: { class: 'lucide' } });
  }

  return container;
}
```

- [ ] **Step 2: 요약 테이블 동적 행(Row) 조작 및 가벼운 스키마 자체 유효성 검사기 구현**

```javascript
// 스키마 가벼운 검증 로직
function verifySchemaCompliance(content, mode) {
  if (mode !== 'schema') return { ok: true, status: 'N/A', css: 'badge-ghost' };
  try {
    const parsed = JSON.parse(content);
    const rawSchema = el('schema-input').value;
    const schema = JSON.parse(rawSchema);

    if (schema.required && Array.isArray(schema.required)) {
      const missingKeys = schema.required.filter(key => !(key in parsed));
      if (missingKeys.length > 0) {
        return { ok: false, status: '누락: ' + missingKeys.join(', '), css: 'badge-warning text-xs' };
      }
    }
    return { ok: true, status: '정상 준수', css: 'badge-success' };
  } catch (e) {
    return { ok: false, status: 'JSON 손상', css: 'badge-error' };
  }
}

function addTablePlaceholderRow(batchId, modelName) {
  const tbody = el('batch-table-body-' + batchId);
  const row = document.createElement('tr');
  row.innerHTML = 
    '  <td class="font-mono text-left font-semibold">' + escapeHtml(modelName) + '</td>'
    + '<td><span class="loading loading-spinner loading-xs"></span></td>'
    + '<td>-</td><td>-</td><td>-</td><td>-</td><td>-</td><td>-</td><td>-</td>';
  tbody.appendChild(row);
  return row;
}

function updateTableSuccessRow(row, model, m, content) {
  const total = m.total_duration_ms ? (m.total_duration_ms / 1000).toFixed(1) + 's' : '-';
  const load = m.load_duration_ms ? (m.load_duration_ms / 1000).toFixed(1) + 's' : '-';
  const evalDur = m.eval_duration_ms ? (m.eval_duration_ms / 1000).toFixed(1) + 's' : '-';
  const inputTok = m.prompt_eval_count != null ? m.prompt_eval_count : '-';
  const outputTok = m.eval_count != null ? m.eval_count : '-';
  const speed = m.tokens_per_second != null ? m.tokens_per_second : '-';

  const schemaCheck = verifySchemaCompliance(content, formatMode);

  row.innerHTML = 
    '  <td class="font-mono text-left font-semibold">' + escapeHtml(model) + '</td>'
    + '<td><span class="badge badge-success badge-sm">성공</span></td>'
    + '<td class="font-semibold">' + total + '</td>'
    + '<td>' + load + '</td>'
    + '<td>' + evalDur + '</td>'
    + '<td>' + inputTok + '</td>'
    + '<td>' + outputTok + '</td>'
    + '<td class="font-semibold text-primary">' + speed + '</td>'
    + '<td><span class="badge badge-sm ' + schemaCheck.css + '">' + escapeHtml(schemaCheck.status) + '</span></td>';
}

function updateTableFailRow(row, model, errorMsg) {
  row.innerHTML = 
    '  <td class="font-mono text-left font-semibold opacity-60">' + escapeHtml(model) + '</td>'
    + '<td><span class="badge badge-error badge-sm">실패</span></td>'
    + '<td colspan="6" class="text-error text-left px-4 text-xs font-mono break-all">' + escapeHtml(errorMsg) + '</td>'
    + '<td>-</td>';
}
```

- [ ] **Step 3: 개별 모델에 대한 상세 응답 카드 구조 고도화**

```javascript
function addDetailCard(batchWrapper, result) {
  const detailsContainer = batchWrapper.querySelector('[id^="batch-details-"]');
  const card = document.createElement('div');
  card.className = 'border border-base-200 rounded-lg p-3 bg-base-50/50 space-y-2';

  let badges = '<span class="badge badge-primary badge-sm font-mono">' + escapeHtml(result.model) + '</span>';
  let bodyHtml;

  if (!result.ok) {
    badges += ' <span class="badge badge-error badge-sm">실패</span>';
    bodyHtml = '<pre class="text-xs text-error whitespace-pre-wrap mt-1 bg-error/10 p-2 rounded max-h-48 overflow-y-auto font-mono">' + escapeHtml(result.error) + '</pre>';
  } else {
    const m = result.metrics || {};
    const schemaCheck = verifySchemaCompliance(result.content, formatMode);
    
    if (schemaCheck.ok) {
      badges += ' <span class="badge badge-success badge-sm">JSON 준수</span>';
    } else {
      badges += ' <span class="badge badge-warning badge-sm">JSON 불완전</span>';
    }

    let display = result.content;
    try { display = JSON.stringify(JSON.parse(result.content), null, 2); } catch (e) { /* 파싱불가시 원문 표출 */ }

    bodyHtml = 
      '<div class="grid grid-cols-2 gap-1 text-[10px] opacity-70 bg-base-200/50 p-1.5 rounded">'
      + '  <div>인풋토큰: ' + (m.prompt_eval_count || '-') + ' / 아웃풋토큰: ' + (m.eval_count || '-') + '</div>'
      + '  <div class="text-right">추론속도: ' + (m.tokens_per_second || '-') + ' tok/s</div>'
      + '</div>'
      + '<pre class="text-[11px] whitespace-pre-wrap overflow-x-auto mt-2 bg-base-300 rounded p-2 max-h-60 overflow-y-auto font-mono">'
      + escapeHtml(display) + '</pre>';
  }

  card.innerHTML = 
    '<div class="flex items-center justify-between border-b border-base-200 pb-1">'
    + '  <div class="flex flex-wrap gap-1">' + badges + '</div>'
    + '</div>' + bodyHtml;

  detailsContainer.appendChild(card);
}
```

- [ ] **Step 4: Git Commit**

```bash
git add suh-ai-server/flask/static/js/ollama-test.js
git commit (m) "feat(ollama-test): 정밀 요약 비교 테이블 및 지표 카드 실시간 주입 고도화 적용"
```

---

## Self-Review Check

1. **Spec Coverage**: 
   - [x] 모델 다중 선택 UI 제공 (Task 1, 2)
   - [x] 순차 벤치마킹 실행 보장 (Task 3)
   - [x] 상세 성능 지표 및 로드 딜레이, 입출력 토큰 분석 (Task 4)
   - [x] 중지 제어 기능 (Task 3)
   - [x] 스키마 준수 정교화 검증 (Task 4)
   - [x] 영구적인 상태 보존 캐싱 (Task 2)
2. **Placeholder Scan**: "TODO"나 "TBD"가 전혀 없으며, 렌더링에 사용되는 complete 코드를 온전히 작성하였습니다.
3. **Consistency**: `ollama-test.html`에서 수정한 컴포넌트의 ID들과 `ollama-test.js`에 설정한 DOM 선택자의 이름이 완벽하게 결합되어 일치합니다.
