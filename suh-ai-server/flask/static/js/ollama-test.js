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
function groupByFamily(models) {
  const groups = {};
  models.forEach(function (m) {
    const fam = window.getActualFamily(m);
    (groups[fam] = groups[fam] || []).push(m);
  });
  return Object.keys(groups)
    .sort()
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

/* ---------- 실시간 다차원 필터링 연산 ---------- */
let filterTimeout = null;

function applyFilters() {
  const query = el('filter-query').value;
  const params = el('filter-params').value;
  const maxSizeStep = parseInt(el('filter-size-slider').value);
  const capability = el('filter-capability').value;
  const source = el('filter-source').value;

  // 슬라이더 뱃지 텍스트 업데이트
  const sizeLabels = ["0.5GB 이하", "1.0GB 이하", "4.0GB 이하", "8.0GB 이하", "12.0GB 이하", "16.0GB 이하", "전체"];
  el('filter-size-badge').textContent = sizeLabels[maxSizeStep] || "전체";

  const filters = {
    query: query,
    params: params,
    maxSizeStep: maxSizeStep,
    capability: capability,
    source: source
  };

  // 패밀리 섹션들을 돌면서 실시간 필터 및 렌더링 클래스 동적 전환
  document.querySelectorAll('#model-checkbox-list .family-section').forEach(section => {
    let visibleCount = 0;
    
    section.querySelectorAll('.model-check').forEach(cb => {
      const modelName = cb.value;
      const m = installedModels.find(item => item.name === modelName);
      const label = cb.closest('label');
      
      if (m && label) {
        const passed = window.filterModelList([m], filters).length > 0;
        if (passed) {
          label.classList.remove('hidden');
          visibleCount++;
        } else {
          label.classList.add('hidden');
        }
      }
    });

    // 자식 체크박스가 전부 필터링되어 숨겨진 경우 패밀리 영역 자체를 숨김 처리
    if (visibleCount > 0) {
      section.classList.remove('hidden');
    } else {
      section.classList.add('hidden');
    }
  });
}

function debounceApplyFilters() {
  if (filterTimeout) clearTimeout(filterTimeout);
  filterTimeout = setTimeout(applyFilters, 50);
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
    const famName = group[0];
    const modelsInGroup = group[1];

    const boxes = modelsInGroup.map(function (m) {
      const sizeStr = m.size ? ' (' + fmtSize(m.size) + ')' : '';
      const isVision = m.name.toLowerCase().includes('vision') || m.name.toLowerCase().includes('-vl') || m.name.toLowerCase().includes('ocr');
      const visionBadge = isVision ? ' <span class="badge badge-info badge-[10px] scale-90 shrink-0">vision</span>' : '';
      const isEmbedding = m.family === 'bert' || m.name.toLowerCase().includes('embedding');
      const embedBadge = isEmbedding ? ' <span class="badge badge-success badge-[10px] scale-90 shrink-0">embed</span>' : '';
      const hfBadge = m.name.toLowerCase().startsWith('hf.co/') ? ' <span class="badge badge-outline badge-[10px] text-[10px] shrink-0 scale-90 opacity-60">HF</span>' : '';
      
      return '<label class="label cursor-pointer gap-2 border border-base-300 rounded-lg px-2.5 py-1 bg-base-100 hover:bg-base-200 transition-colors shrink-0">'
        + '  <input type="checkbox" class="checkbox checkbox-xs model-check" value="' + escapeHtml(m.name) + '">'
        + '  <span class="font-mono text-xs break-all">' + escapeHtml(m.name) + sizeStr + '</span>'
        +   visionBadge + embedBadge + hfBadge
        + '</label>';
    }).join('');

    return '<div class="w-full family-section" data-family="' + escapeHtml(famName) + '">'
      + '  <div class="text-xs font-semibold opacity-60 mt-1 mb-1">'
      + '    ' + escapeHtml(famName) + ' <span class="badge badge-ghost badge-xs">' + modelsInGroup.length + '</span>'
      + '  </div>'
      + '  <div class="flex flex-wrap gap-1.5">' + boxes + '</div>'
      + '</div>';
  }).join('');

  // 체크박스 클릭 이벤트 시 상태 저장
  document.querySelectorAll('.model-check').forEach(cb => {
    cb.addEventListener('change', saveState);
  });

  // 즉시 동적 실시간 필터 적용
  applyFilters();
}

/* ---------- 로컬 상태 관리 (localStorage) ---------- */
function saveState() {
  const selectedModels = Array.from(document.querySelectorAll('.model-check:checked')).map(cb => cb.value);
  const badge = el('active-scenario-badge');
  const activeScenario = badge && !badge.classList.contains('hidden') ? badge.textContent : null;
  const state = {
    selectedModels: selectedModels,
    temperature: el('temperature').value,
    formatMode: formatMode,
    systemPrompt: el('system-prompt').value,
    userPrompt: el('user-prompt').value,
    schemaInput: el('schema-input').value,
    activeScenario: activeScenario,
    autoUnload: el('auto-unload-toggle').checked,
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
    if (state.activeScenario) {
      const badge = el('active-scenario-badge');
      if (badge) {
        badge.textContent = state.activeScenario;
        badge.classList.remove('hidden');
      }
    }
    if (state.autoUnload != null) {
      el('auto-unload-toggle').checked = state.autoUnload;
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
  const system = el('system-prompt').value.trim();
  const temperature = parseFloat(el('temperature').value) || 0.0;
  const schemaDefinition = formatMode === 'schema' ? el('schema-input').value : null;

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

  // 1. 백엔드 DB 마스터 배치 세션 생성
  let batchId = null;
  let isDbBound = false;
  try {
    const batchResp = await apiFetch(OLLAMA_API + '/benchmark/batch', {
      method: 'POST',
      body: JSON.stringify({
        prompt: prompt,
        system: system,
        temperature: temperature,
        format_mode: formatMode,
        schema_definition: schemaDefinition
      })
    });
    if (batchResp.ok) {
      const bData = await batchResp.json();
      batchId = bData.batch_id;
      isDbBound = true;
    }
  } catch (e) {
    console.warn("DB master batch creation failed (fail-open target):", e);
  }

  // 만약 DB가 꺼져있거나 미설정인 경우 로컬 시퀀스 폴백
  if (!batchId) {
    resultSeq += 1;
    batchId = resultSeq;
  }

  // 동적 배치 컨테이너 추가
  const batchWrapper = addBatchContainer(batchId, prompt, formatMode);
  
  // 데이터 속성에 바인딩하여 훗날 재시도나 다운로드 시 사용
  batchWrapper.dataset.batchId = batchId;
  batchWrapper.dataset.prompt = prompt;
  batchWrapper.dataset.systemPrompt = system;
  batchWrapper.dataset.temperature = temperature;
  batchWrapper.dataset.formatMode = formatMode;
  batchWrapper.dataset.dbBound = isDbBound ? 'true' : 'false';
  if (schemaDefinition) batchWrapper.dataset.schemaDefinition = schemaDefinition;

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
        temperature: temperature,
        auto_unload: el('auto-unload-toggle').checked,
      };
      if (system) reqBody.system = system;
      if (formatMode === 'json') reqBody.format = 'json';
      if (formatMode === 'schema') reqBody.format = JSON.parse(schemaDefinition);

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
        const metrics = data.metrics || { total_duration_ms: durationMs };

        // 요약 테이블 행 업데이트 및 상세 카드 추가
        const schemaCheck = verifySchemaCompliance(data.content, formatMode, schemaDefinition);
        updateTableSuccessRow(row, model, metrics, data.content, schemaCheck);
        addDetailCard(batchWrapper, { ok: true, model: model, mode: formatMode, content: data.content, metrics: metrics, schemaCheck: schemaCheck });

        // 실시간 원격 DB UPSERT 전송 (fail-open)
        await saveResultToDatabase(batchId, model, 'success', data.content, metrics, schemaCheck.status, isDbBound);

      } catch (err) {
        if (err.name === 'AbortError') {
          updateTableFailRow(row, model, '중단됨');
          await saveResultToDatabase(batchId, model, 'abort', '사용자 중단', null, 'N/A', isDbBound);
          break;
        }
        updateTableFailRow(row, model, err.message);
        addDetailCard(batchWrapper, { ok: false, model: model, mode: formatMode, error: err.message });
        
        // 실시간 실패 내역 DB 전송
        await saveResultToDatabase(batchId, model, 'fail', err.message, null, 'FAIL', isDbBound);
      }

      // [OOM 정복 핵심 장치] 실행 완료된 모델 VRAM에서 강제 Unload 해제 (토글 ON일 때만 기동)
      if (el('auto-unload-toggle').checked) {
        try {
          await apiFetch(OLLAMA_API + '/control/unload', {
            method: 'POST',
            body: JSON.stringify({ model: model })
          });
        } catch (e) {
          console.warn("Auto-unload model " + model + " failed (fail-open):", e);
        }
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
    loadHistory(); // 벤치마크 루프 완결 시 과거 이력 목록 비동기 갱신
  }
}

async function saveResultToDatabase(batchId, modelName, status, content, metrics, schemaStatus, isDbBound) {
  if (!isDbBound || !batchId) return;
  try {
    await apiFetch(OLLAMA_API + '/benchmark/result', {
      method: 'POST',
      body: JSON.stringify({
        batch_id: batchId,
        model_name: modelName,
        status: status,
        response_content: content,
        metrics: metrics,
        schema_compliance: schemaStatus
      })
    });
  } catch (e) {
    console.warn("DB result upsert logging failed (fail-open):", e);
  }
}

/* ---------- 단일/일괄 실패 모델 재실행 (Retry) 로직 ---------- */
async function retryFailedModels(batchId) {
  const container = el('batch-run-' + batchId);
  if (!container || running) return;

  const failedRows = Array.from(container.querySelectorAll('tbody tr')).filter(tr => {
    const statusCell = tr.querySelectorAll('td')[1];
    return statusCell && statusCell.innerText.includes('실패');
  });

  if (!failedRows.length) {
    showToast('재시도할 실패한 모델이 없습니다.', 'info');
    return;
  }

  const failedModelNames = failedRows.map(tr => tr.querySelectorAll('td')[0].innerText.trim());
  showToast(failedModelNames.length + '개의 실패 모델 재시도를 시작합니다.', 'info');

  for (const model of failedModelNames) {
    await retrySingleModel(batchId, model);
  }
}

async function retrySingleModel(batchId, modelName) {
  const container = el('batch-run-' + batchId);
  if (!container) return;

  const isDbBound = container.dataset.dbBound === 'true';

  // 카드 보존 데이터셋으로부터 당시 스펙 완벽 복원
  const prompt = container.dataset.prompt;
  const system = container.dataset.systemPrompt || null;
  const temperature = parseFloat(container.dataset.temperature) || 0.0;
  const formatModeText = container.dataset.formatMode;
  const schemaDef = container.dataset.schemaDefinition || null;

  // UI 스피너 전환
  let targetRow = null;
  container.querySelectorAll('tbody tr').forEach(tr => {
    if (tr.querySelectorAll('td')[0].innerText.trim() === modelName) targetRow = tr;
  });

  if (!targetRow) return;
  targetRow.querySelectorAll('td')[1].innerHTML = '<span class="loading loading-spinner loading-xs"></span>';

  const reqBody = {
    model: modelName,
    prompt: prompt,
    temperature: temperature,
    auto_unload: el('auto-unload-toggle').checked,
  };
  if (system) reqBody.system = system;
  if (formatModeText === 'json') reqBody.format = 'json';
  if (formatModeText === 'schema' && schemaDef) reqBody.format = JSON.parse(schemaDef);

  const start = performance.now();
  try {
    const resp = await apiFetch(OLLAMA_API + '/chat', {
      method: 'POST',
      body: JSON.stringify(reqBody)
    });
    const data = await resp.json();
    if (!resp.ok) throw new Error(data.error || 'HTTP ' + resp.status);

    const durationMs = performance.now() - start;
    const metrics = data.metrics || { total_duration_ms: durationMs };
    const schemaCheck = verifySchemaCompliance(data.content, formatModeText, schemaDef);

    // 요약 테이블 행 업데이트
    updateTableSuccessRow(targetRow, modelName, metrics, data.content, schemaCheck);

    // 기존 세부 카드 삭제 및 갱신
    removeExistingDetailCard(container, modelName);
    addDetailCard(container, { ok: true, model: modelName, mode: formatModeText, content: data.content, metrics: metrics, schemaCheck: schemaCheck });

    // DB UPSERT 처리
    await saveResultToDatabase(batchId, modelName, 'success', data.content, metrics, schemaCheck.status, isDbBound);
    showToast(modelName + ' 재시도 성공!', 'success');

  } catch (e) {
    updateTableFailRow(targetRow, modelName, e.message);
    removeExistingDetailCard(container, modelName);
    addDetailCard(container, { ok: false, model: modelName, mode: formatModeText, error: e.message });

    await saveResultToDatabase(batchId, modelName, 'fail', e.message, null, 'FAIL', isDbBound);
    showToast(modelName + ' 재시도 실패: ' + e.message, 'error');
  }
}

function removeExistingDetailCard(batchWrapper, modelName) {
  const detailsContainer = batchWrapper.querySelector('[id^="batch-details-"]');
  if (!detailsContainer) return;
  const cards = detailsContainer.querySelectorAll('& > div');
  cards.forEach(card => {
    const badge = card.querySelector('.badge-primary');
    if (badge && badge.innerText.trim() === modelName) {
      card.remove();
    }
  });
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
    + '  <div class="flex items-center gap-1.5 shrink-0">'
    + '    <!-- 일괄 실패 모델 재실행 버튼 -->'
    + '    <button class="btn btn-warning btn-xs gap-1 btn-retry-failed hidden" title="실패한 모든 모델 재시험 기동">'
    + '      <i data-lucide="rotate-ccw" class="size-3"></i>실패모델 재실행'
    + '    </button>'
    + '    <!-- 클립보드 복사 버튼 -->'
    + '    <button class="btn btn-ghost btn-xs text-primary px-1.5 btn-export-copy" title="AI 보고서 클립보드 복사" data-batch-id="' + batchId + '">'
    + '      <i data-lucide="copy" class="size-3.5"></i>'
    + '    </button>'
    + '    <!-- 마크다운 다운로드 버튼 -->'
    + '    <button class="btn btn-ghost btn-xs text-primary px-1.5 btn-export-download" title="마크다운 파일 다운로드" data-batch-id="' + batchId + '">'
    + '      <i data-lucide="download" class="size-3.5"></i>'
    + '    </button>'
    + '    <span class="badge badge-primary badge-outline text-xs">' + modeLabel + '</span>'
    + '  </div>'
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

  // 동적 생성된 버튼 바인딩
  bindExportEvents(container, batchId);

  return container;
}

function verifySchemaCompliance(content, mode, rawSchema) {
  if (mode !== 'schema') return { ok: true, status: 'N/A', css: 'badge-ghost opacity-60' };
  try {
    const parsed = JSON.parse(content);
    const schemaString = rawSchema || el('schema-input').value;
    const schema = JSON.parse(schemaString);

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

function updateTableSuccessRow(row, model, m, content, schemaCheck) {
  const total = m.total_duration_ms ? (m.total_duration_ms / 1000).toFixed(1) + 's' : '-';
  const load = m.load_duration_ms ? (m.load_duration_ms / 1000).toFixed(1) + 's' : '-';
  const evalDur = m.eval_duration_ms ? (m.eval_duration_ms / 1000).toFixed(1) + 's' : '-';
  const inputTok = m.prompt_eval_count != null ? m.prompt_eval_count : '-';
  const outputTok = m.eval_count != null ? m.eval_count : '-';
  const speed = m.tokens_per_second != null ? m.tokens_per_second : '-';

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
  const batchId = row.parentNode.id.replace('batch-table-body-', '');
  row.innerHTML = 
    '  <td class="font-mono text-left font-semibold opacity-60">' + escapeHtml(model) + '</td>'
    + '<td class="flex items-center justify-center gap-1">'
    + '  <span class="badge badge-error badge-sm">실패</span>'
    + '  <button class="btn btn-ghost btn-xs text-warning btn-single-retry" title="이 모델만 재시험 기동" data-model="' + escapeHtml(model) + '">'
    + '    <i data-lucide="rotate-ccw" class="size-3"></i>'
    + '  </button>'
    + '</td>'
    + '<td colspan="6" class="text-error text-left px-4 text-xs font-mono break-all">' + escapeHtml(errorMsg) + '</td>'
    + '<td>-</td>';

  // 단일 재시도 버튼 이벤트 바인딩
  const retryBtn = row.querySelector('.btn-single-retry');
  if (retryBtn) {
    retryBtn.addEventListener('click', function() {
      retrySingleModel(batchId, model);
    });
  }

  // 카드 내 일괄 재시도 버튼 노출 처리
  const card = el('batch-run-' + batchId);
  if (card) {
    const batchRetryBtn = card.querySelector('.btn-retry-failed');
    if (batchRetryBtn) {
      batchRetryBtn.classList.remove('hidden');
    }
  }

  if (typeof lucide !== 'undefined') {
    lucide.createIcons({ attrs: { class: 'lucide' } });
  }
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
    const schemaCheck = result.schemaCheck || verifySchemaCompliance(result.content, result.mode, batchWrapper.dataset.schemaDefinition);

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

/* ---------- 벤치마크 결과 마크다운 보고서 내보내기 (복사 및 Blob 다운로드) ---------- */
function generateBatchMarkdownReport(batchId) {
  const container = el('batch-run-' + batchId);
  if (!container) return '';

  const titleEl = container.querySelector('h3');
  const prompt = container.dataset.prompt || '';
  const system = container.dataset.systemPrompt || '없음';
  const temp = container.dataset.temperature || '0';
  const formatModeText = container.dataset.formatMode || 'none';

  const batchTitle = titleEl ? titleEl.innerText.trim() : '배치 테스트 #' + batchId;
  const now = new Date();
  const dateStr = now.getFullYear() + '년 ' + (now.getMonth() + 1) + '월 ' + now.getDate() + '일 ' 
                + now.getHours() + '시 ' + now.getMinutes() + '분 ' + now.getSeconds() + '초';

  let md = '# Ollama Structured Output 벤치마크 결과 보고서 (' + batchTitle + ')\n\n';
  md += '- **수행 일시**: ' + dateStr + '\n';
  md += '- **포맷 모드**: ' + formatModeText + '\n';
  md += '- **설정 온도 (Temperature)**: ' + temp + '\n';
  md += '- **시스템 지침**: "' + system + '"\n';
  md += '- **테스트 프롬프트**: ' + prompt + '\n\n';

  // 1. 요약 테이블 긁어오기
  md += '## 1. 정량 지표 종합 비교\n\n';
  md += '| 모델 | 상태 | 총 시간 | 로드 지연 | 추론 시간 | 입력 토큰 | 출력 토큰 | 추론 속도 | Schema 준수 여부 |\n';
  md += '| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |\n';

  const rows = container.querySelectorAll('tbody tr');
  rows.forEach(tr => {
    const cells = tr.querySelectorAll('td');
    if (cells.length >= 9) {
      const model = cells[0].innerText.trim();
      const status = cells[1].innerText.trim();
      const total = cells[2].innerText.trim();
      const load = cells[3].innerText.trim();
      const evalDur = cells[4].innerText.trim();
      const inputTok = cells[5].innerText.trim();
      const outputTok = cells[6].innerText.trim();
      const speed = cells[7].innerText.trim();
      const schema = cells[8].innerText.trim();

      md += '| ' + model + ' | ' + status + ' | ' + total + ' | ' + load + ' | ' + evalDur + ' | ' + inputTok + ' | ' + outputTok + ' | ' + speed + ' | ' + schema + ' |\n';
    }
  });
  md += '\n';

  // 2. 모델별 생성 상세 응답 긁어오기
  md += '## 2. 모델별 세부 출력 내역\n\n';
  const detailCards = container.querySelectorAll('[id^="batch-details-"] > div');
  detailCards.forEach(card => {
    const modelBadge = card.querySelector('.badge-primary');
    const modelName = modelBadge ? modelBadge.innerText.trim() : '알 수 없는 모델';

    const statusBadge = card.querySelector('.badge-success, .badge-warning, .badge-error');
    const statusText = statusBadge ? statusBadge.innerText.trim() : '';

    const metricsEl = card.querySelector('.grid-cols-2');
    const metricsText = metricsEl ? metricsEl.innerText.replace(/\s+/g, ' ').trim() : '';

    const codeBlock = card.querySelector('pre');
    const responseJson = codeBlock ? codeBlock.innerText.trim() : '';

    md += '### 🤖 ' + modelName + '\n';
    if (statusText) md += '- **상태**: ' + statusText + '\n';
    if (metricsText) md += '- **지표 요약**: ' + metricsText + '\n';
    md += '- **구조화 생성 결과 (JSON)**:\n';
    md += '```json\n' + responseJson + '\n```\n\n';
  });

  md += '---\n';
  return md;
}

function downloadMarkdownReport(batchId) {
  const md = generateBatchMarkdownReport(batchId);
  if (!md) { showToast('보고서 데이터를 생성할 수 없습니다.', 'error'); return; }

  const todayStr = new Date().toISOString().slice(0, 10).replace(/-/g, '');
  const fileName = 'ollama_benchmark_batch_' + batchId + '_' + todayStr + '.md';

  const blob = new Blob([md], { type: 'text/markdown;charset=utf-8' });
  const url = URL.createObjectURL(blob);

  const a = document.createElement('a');
  a.href = url;
  a.download = fileName;
  document.body.appendChild(a);
  a.click();

  setTimeout(() => {
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  }, 100);

  showToast('보고서 파일 다운로드가 시작되었습니다.', 'success');
}

function copyReportToClipboard(batchId) {
  const md = generateBatchMarkdownReport(batchId);
  if (!md) { showToast('복사할 보고서 데이터가 없습니다.', 'error'); return; }

  if (navigator.clipboard && window.isSecureContext) {
    navigator.clipboard.writeText(md)
      .then(() => {
        showToast('보고서가 클립보드에 복사되었습니다! AI 도구와 대화해 보세요.', 'success');
      })
      .catch(err => {
        console.warn('Clipboard API failed, falling back...', err);
        fallbackCopyTextToClipboard(md);
      });
  } else {
    fallbackCopyTextToClipboard(md);
  }
}

function fallbackCopyTextToClipboard(text) {
  const textArea = document.createElement("textarea");
  textArea.value = text;
  
  textArea.style.top = "0";
  textArea.style.left = "0";
  textArea.style.position = "fixed";
  textArea.style.opacity = "0";

  document.body.appendChild(textArea);
  textArea.focus();
  textArea.select();

  try {
    const successful = document.execCommand('copy');
    if (!successful) throw new Error('copy command returned false');
    showToast('보고서가 클립보드에 복사되었습니다! (Fallback)', 'success');
  } catch (err) {
    showToast('클립보드 복사에 실패했습니다.', 'error');
  }

  document.body.removeChild(textArea);
}

function bindExportEvents(cardContainer, batchId) {
  const copyBtn = cardContainer.querySelector('.btn-export-copy');
  const downloadBtn = cardContainer.querySelector('.btn-export-download');
  const retryFailedBtn = cardContainer.querySelector('.btn-retry-failed');

  if (copyBtn) {
    copyBtn.addEventListener('click', function() {
      copyReportToClipboard(batchId);
    });
  }
  if (downloadBtn) {
    downloadBtn.addEventListener('click', function() {
      downloadMarkdownReport(batchId);
    });
  }
  if (retryFailedBtn) {
    retryFailedBtn.addEventListener('click', function() {
      retryFailedModels(batchId);
    });
  }
}

/* ---------- 과거 벤치마크 이력 조회 & Lazy Loading 복원 ---------- */
async function loadHistory() {
  const container = el('history-list');
  try {
    const resp = await apiFetch(OLLAMA_API + '/benchmark/history');
    const data = await resp.json();
    if (!resp.ok) throw new Error(data.error || '이력 조회 실패');

    if (!data.success || !data.batches || !data.batches.length) {
      container.innerHTML = '<p id="history-empty" class="text-sm opacity-60">저장된 과거 이력이 없습니다.</p>';
      return;
    }

    container.innerHTML = data.batches.map(b => {
      const dateStr = b.created_at ? b.created_at.slice(0, 19).replace('T', ' ') : '-';
      const promptSummary = b.prompt.length > 55 ? b.prompt.slice(0, 55) + '...' : b.prompt;
      const schemaBadge = b.format_mode === 'schema' ? ' <span class="badge badge-primary badge-xs">Schema</span>' : '';
      
      return '<details class="collapse collapse-arrow border border-base-300 bg-base-100 rounded-xl" data-batch-id="' + b.id + '">'
        + '  <summary class="collapse-title text-sm font-medium flex items-center justify-between gap-4 py-3 min-h-0">'
        + '    <div class="flex flex-wrap items-center gap-2 flex-1 min-w-0">'
        + '      <span class="badge badge-neutral font-mono text-xs">#' + b.id + '</span>'
        + '      <span class="text-xs opacity-50">' + dateStr + '</span>'
        + '      <span class="text-xs font-semibold opacity-70 truncate max-w-sm" title="' + escapeHtml(b.prompt) + '">"' + escapeHtml(promptSummary) + '"</span>'
        + '    </div>'
        + '    <div class="flex items-center gap-1.5 mr-6 shrink-0">'
        + '      <button class="btn btn-outline btn-primary btn-xs btn-history-reuse" data-batch-id="' + b.id + '">이 조건으로 실험</button>'
        + '      ' + schemaBadge
        + '    </div>'
        + '  </summary>'
        + '  <div class="collapse-content space-y-4 pt-2 border-t border-base-200 hidden-initially" id="history-content-' + b.id + '">'
        + '    <div class="flex items-center justify-center p-4">'
        + '      <span class="loading loading-spinner loading-md text-primary"></span>'
        + '      <span class="text-sm ml-2 opacity-70">세부 지표를 불러오는 중...</span>'
        + '    </div>'
        + '  </div>'
        + '</details>';
    }).join('');

    // 이벤트 바인딩
    container.querySelectorAll('details').forEach(det => {
      det.addEventListener('toggle', function() {
        if (det.open) loadBatchDetailsOnExpand(det.dataset.batchId);
      });
    });

    container.querySelectorAll('.btn-history-reuse').forEach(btn => {
      btn.addEventListener('click', function(e) {
        e.preventDefault();
        e.stopPropagation();
        reuseHistoryConfig(btn.dataset.batchId);
      });
    });

    if (typeof lucide !== 'undefined') {
      lucide.createIcons({ attrs: { class: 'lucide' } });
    }
  } catch (e) {
    container.innerHTML = '<p class="text-error text-sm">과거 이력 로드 중 오류 발생: ' + escapeHtml(e.message) + '</p>';
  }
}

async function loadBatchDetailsOnExpand(batchId) {
  const contentWrap = el('history-content-' + batchId);
  // 이미 로드 완료한 아코디언 상태면 API 재조회 스킵
  if (!contentWrap || contentWrap.dataset.loaded === 'true') return;

  try {
    const resp = await apiFetch(OLLAMA_API + '/benchmark/history/' + batchId);
    const data = await resp.json();
    if (!resp.ok) throw new Error(data.error || '세부 정보 패치 실패');

    if (!data.success || !data.results) {
      contentWrap.innerHTML = '<p class="text-error text-xs">상세 데이터 패치 실패</p>';
      return;
    }

    // 마스터 정보 갱신을 위해 상위 뎬 배치의 마스터 맵 정보 긁어오기
    const mainResp = await apiFetch(OLLAMA_API + '/benchmark/history');
    const mainData = await mainResp.json();
    const batchMaster = (mainData.batches || []).find(b => String(b.id) === String(batchId));

    if (!batchMaster) {
      contentWrap.innerHTML = '<p class="text-error text-xs">마스터 정보 획득 실패</p>';
      return;
    }

    // 마크다운 복사용 데이터 주입을 위해 컨테이너 카드에 dataset 바인딩
    const detailsEl = document.querySelector('details[data-batch-id="' + batchId + '"]');
    detailsEl.id = 'batch-run-' + batchId;
    detailsEl.dataset.prompt = batchMaster.prompt;
    detailsEl.dataset.systemPrompt = batchMaster.system_prompt || '';
    detailsEl.dataset.temperature = batchMaster.temperature;
    detailsEl.dataset.formatMode = batchMaster.format_mode;
    detailsEl.dataset.dbBound = 'true'; // 과거 이력은 항상 DB 바운드 상태
    if (batchMaster.schema_definition) detailsEl.dataset.schemaDefinition = batchMaster.schema_definition;

    const modeLabel = MODE_LABELS[batchMaster.format_mode] || batchMaster.format_mode;

    // 요약 테이블 및 카드 리스트 템플릿 복원 생성
    contentWrap.innerHTML = 
      '<div class="flex items-center justify-between border-b border-base-200 pb-1.5">'
      + '  <div class="text-xs opacity-60 font-semibold">'
      + '    설정 온도: ' + batchMaster.temperature + ' | 시스템: "' + (batchMaster.system_prompt || '없음') + '"'
      + '  </div>'
      + '  <div class="flex items-center gap-1.5 shrink-0">'
      + '    <button class="btn btn-warning btn-xs gap-1 btn-retry-failed hidden" title="실패한 모든 모델 재시험 기동">'
      + '      <i data-lucide="rotate-ccw" class="size-3"></i>실패모델 재실행'
      + '    </button>'
      + '    <button class="btn btn-ghost btn-xs text-primary px-1.5 btn-export-copy" title="AI 보고서 클립보드 복사" data-batch-id="' + batchId + '">'
      + '      <i data-lucide="copy" class="size-3.5"></i>'
      + '    </button>'
      + '    <button class="btn btn-ghost btn-xs text-primary px-1.5 btn-export-download" title="마크다운 파일 다운로드" data-batch-id="' + batchId + '">'
      + '      <i data-lucide="download" class="size-3.5"></i>'
      + '    </button>'
      + '    <span class="badge badge-primary badge-outline text-xs">' + modeLabel + '</span>'
      + '  </div>'
      + '</div>'
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
      + '<div class="grid grid-cols-1 md:grid-cols-2 gap-3" id="batch-details-' + batchId + '"></div>';

    const tbody = el('batch-table-body-' + batchId);
    let anyFailed = false;

    data.results.forEach(res => {
      const row = document.createElement('tr');
      tbody.appendChild(row);

      if (res.status === 'success') {
        const schemaCheck = verifySchemaCompliance(res.response_content, batchMaster.format_mode, batchMaster.schema_definition);
        updateTableSuccessRow(row, res.model_name, res.metrics, res.response_content, schemaCheck);
        addDetailCard(detailsEl, { ok: true, model: res.model_name, mode: batchMaster.format_mode, content: res.response_content, metrics: res.metrics, schemaCheck: schemaCheck });
      } else {
        updateTableFailRow(row, res.model_name, res.response_content);
        addDetailCard(detailsEl, { ok: false, model: res.model_name, mode: batchMaster.format_mode, error: res.response_content });
        anyFailed = true;
      }
    });

    if (anyFailed) {
      const batchRetryBtn = contentWrap.querySelector('.btn-retry-failed');
      if (batchRetryBtn) batchRetryBtn.classList.remove('hidden');
    }

    contentWrap.dataset.loaded = 'true';
    bindExportEvents(contentWrap, batchId);

    if (typeof lucide !== 'undefined') {
      lucide.createIcons({ attrs: { class: 'lucide' } });
    }
  } catch (e) {
    contentWrap.innerHTML = '<p class="text-error text-xs p-4">세부 지표 로딩 오류: ' + escapeHtml(e.message) + '</p>';
  }
}

function reuseHistoryConfig(batchId) {
  const det = document.querySelector('details[data-batch-id="' + batchId + '"]');
  if (!det) return;

  const prompt = det.dataset.prompt;
  const system = det.dataset.systemPrompt || '';
  const temperature = det.dataset.temperature || '0';
  const formatModeText = det.dataset.formatMode || 'none';
  const schemaDef = det.dataset.schemaDefinition || '';

  if (prompt) el('user-prompt').value = prompt;
  el('system-prompt').value = system;
  el('temperature').value = temperature;
  setFormatMode(formatModeText);
  if (schemaDef) {
    el('schema-input').value = schemaDef;
    validateSchema();
  }

  saveState();
  window.scrollTo({ top: 0, behavior: 'smooth' });
  showToast('과거 실험 설정으로 편집기 입력을 로드 복원하였습니다.', 'success');
}

/* ---------- AI 시나리오 설계 및 임포트 ---------- */
const GUIDELINE_TEMPLATE = `귀하는 최고의 구조화 데이터(Structured Output) 설계 전문가입니다.
사용자가 테스트하고 싶어 하는 시나리오를 주면, 해당 시나리오를 로컬 LLM(Ollama)에서 테스트할 수 있도록 완벽한 JSON 형식으로 기획 및 작성해 주세요.

[포맷(format)별 출력 규격]
1. format이 "schema"인 경우:
   - 엄격한 구조 데이터 필요 시 적용.
   - "schema" 필드에 최상위 "type": "object" 형태의 유효한 JSON Schema를 필수로 기입해야 함.
2. format이 "json"인 경우:
   - 자유로운 JSON 형식이 필요하나 엄격한 규격을 제어하지 않을 때 적용.
   - "schema" 필드는 null 처리.
3. format이 "none"인 경우:
   - 일반 줄글 텍스트 답변이 필요할 때 적용.
   - "schema" 필드는 null 처리.

[반환 형식 규격]
반드시 아래 JSON 형식으로 작성해야 하며, 다른 부가 설명 없이 마크다운 코드 블록(\`\`\`json ... \`\`\`)만 깔끔하게 출력해야 합니다.

{
  "title": "[설계하려는 시나리오의 직관적인 제목]",
  "temperature": 0.2, // 0.0 ~ 2.0 사이의 정밀도 선택
  "format": "schema", // "schema", "json", "none" 중 하나
  "system_prompt": "[AI가 가져야 할 구체적인 역할 및 지침]",
  "user_prompt": "[테스트를 위해 AI에게 전달할 유저 메시지 또는 원본 데이터]",
  "schema": { ...JSON Schema 객체 또는 format이 schema가 아니면 null... }
}

내가 요청하는 시나리오 주제는 다음과 같습니다:
" 여기에 원하는 테스트 주제(예: 영수증 파싱, 뉴스 요약 등)를 적은 뒤 이 프롬프트 전체를 AI에 보내세요! "`;

function initScenarioModal() {
  const guidelineArea = el('guideline-prompt-text');
  if (guidelineArea) {
    guidelineArea.value = GUIDELINE_TEMPLATE;
  }

  const copyBtn = el('copy-guideline-btn');
  if (copyBtn) {
    copyBtn.addEventListener('click', () => {
      navigator.clipboard.writeText(guidelineArea.value).then(() => {
        showToast('AI 가이드라인 프롬프트가 복사되었습니다. 외부 AI 창에 붙여넣으세요!', 'success');
      });
    });
  }

  const applyBtn = el('apply-scenario-btn');
  if (applyBtn) {
    applyBtn.addEventListener('click', applyScenarioJson);
  }
  
  const exportBtn = el('export-scenario-btn');
  if (exportBtn) {
    exportBtn.addEventListener('click', exportCurrentToScenarioJson);
  }
}

function applyScenarioJson() {
  const inputEl = el('scenario-import-input');
  if (!inputEl) return;
  const rawInput = inputEl.value.trim();
  const errBox = el('scenario-import-error');
  if (!errBox) return;
  errBox.classList.add('hidden');

  try {
    if (!rawInput) {
      throw new Error('입력된 시나리오가 없습니다.');
    }
    // 마크다운 백틱 코드 블록이 섞여 있을 경우를 대비한 가드 클렌징
    let cleanJson = rawInput;
    if (cleanJson.startsWith('```')) {
      cleanJson = cleanJson.replace(/^```json\s*/, '').replace(/```$/, '').trim();
    }

    const data = JSON.parse(cleanJson);

    // 필수 필드 무결성 검증
    if (!data.format || !data.user_prompt) {
      throw new Error('필수 속성(format, user_prompt)이 누락되었습니다.');
    }

    // 1) 포맷 모드 설정
    setFormatMode(data.format);

    // 2) 시스템 및 유저 프롬프트 주입
    el('system-prompt').value = data.system_prompt || '';
    el('user-prompt').value = data.user_prompt;

    // 3) temperature 주입
    if (data.temperature != null) {
      el('temperature').value = data.temperature;
    }

    // 4) JSON Schema 주입
    if (data.format === 'schema' && data.schema) {
      el('schema-input').value = JSON.stringify(data.schema, null, 2);
    } else if (data.format !== 'schema') {
      el('schema-input').value = '';
    }

    // 5) 제목 배지 동적 적용
    const badge = el('active-scenario-badge');
    if (badge) {
      if (data.title) {
        badge.textContent = '시나리오: ' + data.title;
        badge.classList.remove('hidden');
      } else {
        badge.classList.add('hidden');
      }
    }

    // 검증 후 상태 저장 및 모달 닫기
    validateSchema();
    saveState();
    const modal = el('scenario-modal');
    if (modal) modal.close();
    showToast(`시나리오 "${data.title || '테스트 구성'}"가 정상적으로 주입되었습니다!`, 'success');

  } catch (e) {
    errBox.textContent = 'JSON 파싱 오류: ' + e.message;
    errBox.classList.remove('hidden');
  }
}

function exportCurrentToScenarioJson() {
  try {
    const badge = el('active-scenario-badge');
    const titleText = badge && !badge.classList.contains('hidden') ? badge.textContent.replace('시나리오: ', '') : "내보낸 시나리오";
    const currentScenario = {
      title: titleText,
      temperature: parseFloat(el('temperature').value) || 0.0,
      format: formatMode,
      system_prompt: el('system-prompt').value,
      user_prompt: el('user-prompt').value,
      schema: formatMode === 'schema' ? JSON.parse(el('schema-input').value || '{}') : null
    };

    const inputEl = el('scenario-import-input');
    if (inputEl) {
      inputEl.value = JSON.stringify(currentScenario, null, 2);
    }
    showToast('현재 입력값이 JSON 포맷으로 생성되어 입력창에 노출되었습니다!', 'success');
  } catch (e) {
    showToast('내보내기 중 오류 발생: ' + e.message, 'error');
  }
}

/* ---------- 초기화 ---------- */
document.addEventListener('DOMContentLoaded', function () {
  initScenarioModal();
  applyPreset('array');
  setFormatMode('schema');
  loadModels();
  loadHistory(); // 과거 벤치마킹 이력 비동기 조회 로드

  el('model-refresh').addEventListener('click', loadModels);
  el('schema-preset').addEventListener('change', function () { applyPreset(this.value); });
  el('schema-input').addEventListener('input', function() {
    validateSchema();
    saveState();
  });
  el('run-btn').addEventListener('click', run);
  el('stop-btn').addEventListener('click', stopExecution);
  el('clear-results').addEventListener('click', clearResults);
  el('history-refresh').addEventListener('click', loadHistory);

  el('model-select-all').addEventListener('click', function() {
    document.querySelectorAll('.model-check').forEach(cb => {
      const label = cb.closest('label');
      if (label && !label.classList.contains('hidden')) {
        cb.checked = true;
      }
    });
    saveState();
  });
  el('model-select-none').addEventListener('click', function() {
    document.querySelectorAll('.model-check').forEach(cb => {
      const label = cb.closest('label');
      if (label && !label.classList.contains('hidden')) {
        cb.checked = false;
      }
    });
    saveState();
  });

  // 다차원 필터링 조작 바인딩
  el('filter-query').addEventListener('input', applyFilters);
  el('filter-params').addEventListener('change', applyFilters);
  el('filter-size-slider').addEventListener('input', debounceApplyFilters);
  el('filter-capability').addEventListener('change', applyFilters);
  el('filter-source').addEventListener('change', applyFilters);

  el('temperature').addEventListener('input', saveState);
  el('system-prompt').addEventListener('input', saveState);
  el('user-prompt').addEventListener('input', saveState);
  el('auto-unload-toggle').addEventListener('change', saveState);

  document.querySelectorAll('#format-mode [data-mode]').forEach(function (btn) {
    btn.addEventListener('click', function () { 
      setFormatMode(btn.dataset.mode); 
      saveState();
    });
  });
});
