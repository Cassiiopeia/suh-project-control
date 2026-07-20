/* Ollama Structured Output 테스트 페이지 로직. base: /admin/ollama-test → API는 ../ollama/* */
const OLLAMA_API = '../ollama';

const SCHEMA_PRESETS = {
  simple: {
    type: 'object',
    properties: {
      title: { type: 'string' },
      summary: { type: 'string' },
    },
    required: ['title', 'summary'],
    additionalProperties: false,
  },
  nested: {
    type: 'object',
    properties: {
      user: {
        type: 'object',
        properties: {
          name: { type: 'string' },
          profile: {
            type: 'object',
            properties: {
              age: { type: 'integer' },
              tags: { type: 'array', items: { type: 'string' } },
            },
            required: ['age', 'tags'],
            additionalProperties: false,
          },
        },
        required: ['name', 'profile'],
        additionalProperties: false,
      },
    },
    required: ['user'],
    additionalProperties: false,
  },
  array: {
    type: 'object',
    properties: {
      title: { type: 'string' },
      steps: {
        type: 'array',
        items: {
          type: 'object',
          properties: {
            order: { type: 'integer' },
            instruction: { type: 'string' },
          },
          required: ['order', 'instruction'],
          additionalProperties: false,
        },
      },
    },
    required: ['title', 'steps'],
    additionalProperties: false,
  },
  enum: {
    type: 'object',
    properties: {
      sentiment: { type: 'string', enum: ['POSITIVE', 'NEUTRAL', 'NEGATIVE'] },
      confidence: { type: 'number' },
      reason: { type: 'string' },
    },
    required: ['sentiment', 'confidence', 'reason'],
    additionalProperties: false,
  },
};

const MODE_LABELS = { none: 'format 없음', json: '"json"', schema: 'JSON Schema' };
const HF_FAMILY = 'HuggingFace';

let formatMode = 'schema';
let running = false;
let resultSeq = 0;
let abortController = null;
let installedModels = []; // 설치 모델 캐시

function el(id) { return document.getElementById(id); }

const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));

/* ---------- 패밀리 분류 및 사이즈 포맷 ---------- */
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

/* ---------- 모델 목록 체크박스 렌더링 ---------- */
async function loadModels() {
  const container = el('model-checkbox-list');
  try {
    const resp = await apiFetch(OLLAMA_API + '/models');
    const data = await resp.json();
    if (!resp.ok) throw new Error(data.error || '모델 목록 조회 실패');
    installedModels = data.models;
    renderModelCheckboxes();
    restoreState(); // 모델 로딩 후 복원 수행
  } catch (e) {
    container.innerHTML = '<span class="text-error text-sm">모델 조회 실패: ' + escapeHtml(e.message) + '</span>';
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
      const visionBadge = isVision ? ' <span class="badge badge-info badge-[10px] scale-90 shrink-0">vision</span>' : '';
      return '<label class="label cursor-pointer gap-2 border border-base-300 rounded-lg px-2.5 py-1 bg-base-100 hover:bg-base-200 transition-colors shrink-0">'
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

  // 체크박스 클릭 이벤트 시 상태 저장
  document.querySelectorAll('.model-check').forEach(cb => {
    cb.addEventListener('change', saveState);
  });
}

/* ---------- 로컬 상태 관리 (localStorage) ---------- */
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

/* ---------- format 모드 / 스키마 ---------- */
function setFormatMode(mode) {
  formatMode = mode;
  document.querySelectorAll('#format-mode [data-mode]').forEach(function (btn) {
    btn.classList.toggle('btn-active', btn.dataset.mode === mode);
  });
  el('schema-section').classList.toggle('hidden', mode !== 'schema');
  validateSchema();
}

function validateSchema() {
  const errBox = el('schema-error');
  if (formatMode !== 'schema') {
    errBox.classList.add('hidden');
    el('run-btn').disabled = running;
    return true;
  }
  try {
    const parsed = JSON.parse(el('schema-input').value);
    if (typeof parsed !== 'object' || parsed === null || Array.isArray(parsed)) {
      throw new Error('스키마는 JSON 객체여야 합니다');
    }
    errBox.classList.add('hidden');
    el('run-btn').disabled = running;
    return true;
  } catch (e) {
    errBox.textContent = 'JSON 오류: ' + e.message;
    errBox.classList.remove('hidden');
    el('run-btn').disabled = true;
    return false;
  }
}

function applyPreset(name) {
  el('schema-input').value = JSON.stringify(SCHEMA_PRESETS[name], null, 2);
  validateSchema();
  saveState();
}

/* ---------- 벤치마크 및 중지 제어 ---------- */
function stopExecution() {
  if (abortController) {
    abortController.abort();
    abortController = null;
    showToast('벤치마크가 사용자에 의해 중지되었습니다.', 'warning');
  }
}

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

  // 동적 배치 컨테이너 추가
  const batchId = ++resultSeq;
  const batchWrapper = addBatchContainer(batchId, prompt, formatMode);

  try {
    for (const model of selectedModels) {
      if (signal.aborted) break;

      currentIdx++;
      const percent = Math.round((currentIdx / totalModels) * 100);
      el('run-progress').value = percent;
      el('run-status-text').textContent = model + ' (' + currentIdx + '/' + totalModels + ') 실행 중...';

      // 테이블 행 프리홀더 추가
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
        const resp = await apiFetch(OLLAMA_API + '/chat', {
          method: 'POST',
          body: JSON.stringify(reqBody),
          signal: signal,
        });

        const data = await resp.json();
        if (!resp.ok) throw new Error(data.error || 'HTTP ' + resp.status);

        const durationMs = performance.now() - modelStart;
        // 요약 테이블 행 업데이트
        updateTableSuccessRow(row, model, data.metrics || { total_duration_ms: durationMs }, data.content);
        // 상세 카드 추가
        addDetailCard(batchWrapper, { ok: true, model: model, mode: formatMode, content: data.content, metrics: data.metrics });

      } catch (err) {
        if (err.name === 'AbortError') {
          updateTableFailRow(row, model, '중단됨');
          break;
        }
        updateTableFailRow(row, model, err.message);
        addDetailCard(batchWrapper, { ok: false, model: model, mode: formatMode, error: err.message });
      }

      // 모델 전환 리로딩을 위한 안정화 딜레이
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

/* ---------- 실시간 요약 비교 테이블 및 지표 카드 그리기 ---------- */
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
    + '      <tr class="bg-base-200/50">'
    + '        <th class="text-left font-semibold">모델</th>'
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
    + '<!-- 개별 상세 응답 카드 목록 -->'
    + '<div class="grid grid-cols-1 md:grid-cols-2 gap-3" id="batch-details-' + batchId + '"></div>';

  el('result-list').prepend(container);
  el('result-count').textContent = el('result-list').children.length;

  if (typeof lucide !== 'undefined') {
    lucide.createIcons({ attrs: { class: 'lucide' } });
  }

  return container;
}

function verifySchemaCompliance(content, mode) {
  if (mode !== 'schema') return { ok: true, status: 'N/A', css: 'badge-ghost opacity-60' };
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

function clearResults() {
  const list = el('result-list');
  list.innerHTML = '<p id="result-empty" class="text-sm opacity-60">아직 실행한 요청이 없습니다. 모델을 바꿔가며 실행하면 결과가 여기 쌓여 비교할 수 있습니다.</p>';
  el('result-count').textContent = '0';
}

/* ---------- 초기화 ---------- */
document.addEventListener('DOMContentLoaded', function () {
  applyPreset('array');
  setFormatMode('schema');
  loadModels();

  el('model-refresh').addEventListener('click', loadModels);
  el('schema-preset').addEventListener('change', function () { applyPreset(this.value); });
  el('schema-input').addEventListener('input', function() {
    validateSchema();
    saveState();
  });
  el('run-btn').addEventListener('click', run);
  el('stop-btn').addEventListener('click', stopExecution);
  el('clear-results').addEventListener('click', clearResults);

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

  document.querySelectorAll('#format-mode [data-mode]').forEach(function (btn) {
    btn.addEventListener('click', function () { 
      setFormatMode(btn.dataset.mode); 
      saveState();
    });
  });
});
