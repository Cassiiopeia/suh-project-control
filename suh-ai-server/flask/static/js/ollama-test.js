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

let formatMode = 'schema';
let running = false;
let resultSeq = 0;

function el(id) { return document.getElementById(id); }

/* ---------- 모델 목록 ---------- */
async function loadModels() {
  const select = el('model-select');
  try {
    const resp = await apiFetch(OLLAMA_API + '/models');
    const data = await resp.json();
    if (!resp.ok) throw new Error(data.error || '모델 목록 조회 실패');
    select.innerHTML = '';
    if (!data.models.length) {
      select.innerHTML = '<option value="">설치된 모델 없음</option>';
      return;
    }
    data.models.forEach(function (m) {
      const opt = document.createElement('option');
      opt.value = m.name;
      const sizeGb = m.size ? (m.size / 1024 / 1024 / 1024).toFixed(1) + 'GB' : '';
      opt.textContent = m.name + (sizeGb ? ' (' + sizeGb + ')' : '');
      select.appendChild(opt);
    });
  } catch (e) {
    select.innerHTML = '<option value="">조회 실패</option>';
    showToast('모델 목록 조회 실패: ' + e.message, 'error');
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
}

/* ---------- 실행 ---------- */
async function run() {
  if (running) return;
  const model = el('model-select').value;
  const prompt = el('user-prompt').value.trim();
  if (!model) { showToast('모델을 선택하세요', 'warning'); return; }
  if (!prompt) { showToast('프롬프트를 입력하세요', 'warning'); return; }
  if (!validateSchema()) return;

  const body = {
    model: model,
    prompt: prompt,
    temperature: parseFloat(el('temperature').value) || 0,
  };
  const system = el('system-prompt').value.trim();
  if (system) body.system = system;
  if (formatMode === 'json') body.format = 'json';
  if (formatMode === 'schema') body.format = JSON.parse(el('schema-input').value);

  running = true;
  el('run-btn').disabled = true;
  el('run-status').classList.remove('hidden');
  const startedAt = performance.now();
  const timer = setInterval(function () {
    el('run-elapsed').textContent = ((performance.now() - startedAt) / 1000).toFixed(1);
  }, 100);

  try {
    const resp = await apiFetch(OLLAMA_API + '/chat', {
      method: 'POST',
      body: JSON.stringify(body),
    });
    const data = await resp.json();
    if (!resp.ok) throw new Error(data.error || 'HTTP ' + resp.status);
    addResult({ ok: true, model: model, mode: formatMode, content: data.content, metrics: data.metrics });
  } catch (e) {
    if (e.message.indexOf('Unauthorized') === -1) {
      addResult({ ok: false, model: model, mode: formatMode, error: e.message });
    }
  } finally {
    clearInterval(timer);
    running = false;
    el('run-status').classList.add('hidden');
    el('run-btn').disabled = false;
    validateSchema();
  }
}

/* ---------- 결과 렌더링 ---------- */
const MODE_LABELS = { none: 'format 없음', json: '"json"', schema: 'JSON Schema' };

function addResult(result) {
  resultSeq += 1;
  el('result-empty') && el('result-empty').remove();

  const card = document.createElement('div');
  card.className = 'border border-base-300 rounded-lg p-3';

  let badges =
    '<span class="badge badge-primary badge-sm">' + escapeHtml(result.model) + '</span>' +
    '<span class="badge badge-ghost badge-sm">' + MODE_LABELS[result.mode] + '</span>';
  let bodyHtml;

  if (!result.ok) {
    badges += '<span class="badge badge-error badge-sm">에러</span>';
    bodyHtml = '<pre class="text-xs text-error whitespace-pre-wrap mt-2">' + escapeHtml(result.error) + '</pre>';
  } else {
    const m = result.metrics || {};
    if (m.total_duration_ms != null) {
      badges += '<span class="badge badge-ghost badge-sm">' + (m.total_duration_ms / 1000).toFixed(1) + 's</span>';
    }
    if (m.tokens_per_second != null) {
      badges += '<span class="badge badge-ghost badge-sm">' + m.tokens_per_second + ' tok/s</span>';
    }
    let display = result.content;
    let parsed = null;
    try { parsed = JSON.parse(result.content); } catch (e) { /* JSON 아님 */ }
    if (parsed !== null) {
      badges += '<span class="badge badge-success badge-sm">유효 JSON</span>';
      display = JSON.stringify(parsed, null, 2);
    } else if (result.mode !== 'none') {
      badges += '<span class="badge badge-warning badge-sm">JSON 파싱 실패</span>';
    }
    bodyHtml = '<pre class="text-xs whitespace-pre-wrap overflow-x-auto mt-2 bg-base-200 rounded p-2">'
      + escapeHtml(display) + '</pre>';
  }

  card.innerHTML =
    '<div class="flex flex-wrap items-center gap-1">'
    + '<span class="text-xs opacity-50 mr-1">#' + resultSeq + '</span>' + badges
    + '</div>' + bodyHtml;

  el('result-list').prepend(card);
  el('result-count').textContent = el('result-list').children.length;
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
  el('schema-input').addEventListener('input', validateSchema);
  el('run-btn').addEventListener('click', run);
  el('clear-results').addEventListener('click', clearResults);
  document.querySelectorAll('#format-mode [data-mode]').forEach(function (btn) {
    btn.addEventListener('click', function () { setFormatMode(btn.dataset.mode); });
  });
});
