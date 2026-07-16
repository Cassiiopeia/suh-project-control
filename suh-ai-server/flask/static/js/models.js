/* 모델 관리 페이지 로직. base: /admin/models → API는 ../models/*, ../ollama/*, ../ocr/* */
const MODELS_API = '../models';

let installedModels = [];   // GET /models/installed 결과 캐시
let pullController = null;  // 진행 중 pull의 AbortController (동시 1건만 허용)
let pullErrorMessage = null;
let benchRunning = false;
let deleteTarget = null;

function el(id) { return document.getElementById(id); }

function fmtSize(bytes) {
  if (!bytes && bytes !== 0) return '-';
  const gb = bytes / 1024 / 1024 / 1024;
  if (gb >= 1) return gb.toFixed(1) + 'GB';
  return (bytes / 1024 / 1024).toFixed(0) + 'MB';
}

/* ---------- 설치된 모델 ---------- */
async function loadInstalled() {
  const body = el('installed-body');
  try {
    const resp = await apiFetch(MODELS_API + '/installed');
    const data = await resp.json();
    if (!resp.ok) throw new Error(data.error || '조회 실패');
    installedModels = data.models;
    el('installed-error').classList.add('hidden');
    renderInstalled();
    renderBenchModels();
  } catch (e) {
    el('installed-error').classList.remove('hidden');
    body.innerHTML = '<tr><td colspan="7" class="text-center opacity-60">조회 실패</td></tr>';
    if (e.message.indexOf('Unauthorized') === -1) {
      showToast('설치 모델 조회 실패: ' + e.message, 'error');
    }
  }
}

function renderInstalled() {
  const body = el('installed-body');
  el('installed-count').textContent = installedModels.length;
  if (!installedModels.length) {
    body.innerHTML = '<tr><td colspan="7" class="text-center opacity-60">설치된 모델이 없습니다. 아래에서 검색해 받아보세요.</td></tr>';
    return;
  }
  body.innerHTML = installedModels.map(function (m) {
    const vision = m.vision ? ' <span class="badge badge-info badge-xs">vision</span>' : '';
    return '<tr>'
      + '<td class="font-mono">' + escapeHtml(m.name) + vision + '</td>'
      + '<td>' + fmtSize(m.size) + '</td>'
      + '<td>' + escapeHtml(m.family || '-') + '</td>'
      + '<td>' + escapeHtml(m.parameter_size || '-') + '</td>'
      + '<td>' + escapeHtml(m.quantization || '-') + '</td>'
      + '<td>' + (m.modified_at ? escapeHtml(m.modified_at.slice(0, 10)) : '-') + '</td>'
      + '<td><button class="btn btn-error btn-xs" data-delete="' + escapeHtml(m.name) + '">삭제</button></td>'
      + '</tr>';
  }).join('');
  body.querySelectorAll('[data-delete]').forEach(function (btn) {
    btn.addEventListener('click', function () { openDeleteModal(btn.dataset.delete); });
  });
}

function openDeleteModal(name) {
  deleteTarget = name;
  el('delete-model-name').textContent = name;
  el('delete-modal').showModal();
}

async function doDelete() {
  if (!deleteTarget) return;
  try {
    const resp = await apiFetch(MODELS_API + '/installed?name=' + encodeURIComponent(deleteTarget), { method: 'DELETE' });
    const data = await resp.json();
    if (!resp.ok) throw new Error(data.error || '삭제 실패');
    showToast(deleteTarget + ' 삭제 완료', 'success');
  } catch (e) {
    if (e.message.indexOf('Unauthorized') === -1) {
      showToast('삭제 실패: ' + e.message, 'error');
    }
  } finally {
    el('delete-modal').close();
    deleteTarget = null;
    loadInstalled();
  }
}

/* ---------- HF 검색 ---------- */
async function searchHf() {
  const q = el('search-input').value.trim();
  if (!q) { showToast('검색어를 입력하세요', 'warning'); return; }
  const body = el('search-body');
  el('search-results-wrap').classList.remove('hidden');
  el('files-wrap').classList.add('hidden');
  body.innerHTML = '<tr><td colspan="4" class="text-center opacity-60">검색 중...</td></tr>';
  try {
    const resp = await apiFetch(MODELS_API + '/search?q=' + encodeURIComponent(q));
    const data = await resp.json();
    if (!resp.ok) throw new Error(data.error || '검색 실패');
    if (!data.results.length) {
      body.innerHTML = '<tr><td colspan="4" class="text-center opacity-60">결과 없음</td></tr>';
      return;
    }
    body.innerHTML = data.results.map(function (r) {
      return '<tr class="cursor-pointer hover" data-repo="' + escapeHtml(r.repo_id) + '">'
        + '<td class="font-mono">' + escapeHtml(r.repo_id) + '</td>'
        + '<td>' + (r.downloads || 0).toLocaleString() + '</td>'
        + '<td>' + (r.likes || 0) + '</td>'
        + '<td>' + (r.updated_at ? escapeHtml(r.updated_at.slice(0, 10)) : '-') + '</td>'
        + '</tr>';
    }).join('');
    body.querySelectorAll('[data-repo]').forEach(function (row) {
      row.addEventListener('click', function () { loadFiles(row.dataset.repo); });
    });
  } catch (e) {
    body.innerHTML = '<tr><td colspan="4" class="text-center text-error">검색 실패</td></tr>';
    if (e.message.indexOf('Unauthorized') === -1) {
      showToast('HF 검색 실패: ' + e.message, 'error');
    }
  }
}

async function loadFiles(repoId) {
  const body = el('files-body');
  el('files-wrap').classList.remove('hidden');
  el('files-repo').textContent = repoId;
  body.innerHTML = '<tr><td colspan="4" class="text-center opacity-60">파일 조회 중...</td></tr>';
  try {
    const resp = await apiFetch(MODELS_API + '/hf/files?repo=' + encodeURIComponent(repoId));
    const data = await resp.json();
    if (!resp.ok) throw new Error(data.error || '파일 조회 실패');
    if (!data.files.length) {
      body.innerHTML = '<tr><td colspan="4" class="text-center opacity-60">GGUF 파일이 없습니다</td></tr>';
      return;
    }
    body.innerHTML = data.files.map(function (f) {
      return '<tr>'
        + '<td class="font-mono text-xs">' + escapeHtml(f.filename) + '</td>'
        + '<td>' + escapeHtml(f.quant || '-') + '</td>'
        + '<td>' + fmtSize(f.size) + '</td>'
        + '<td><button class="btn btn-primary btn-xs" data-pull="' + escapeHtml(f.ollama_name) + '">받기</button></td>'
        + '</tr>';
    }).join('');
    body.querySelectorAll('[data-pull]').forEach(function (btn) {
      btn.addEventListener('click', function () { startPull(btn.dataset.pull); });
    });
  } catch (e) {
    body.innerHTML = '<tr><td colspan="4" class="text-center text-error">' + escapeHtml(e.message) + '</td></tr>';
  }
}

/* ---------- 다운로드 (pull) ---------- */
async function startPull(name) {
  if (pullController) { showToast('이미 다운로드가 진행 중입니다', 'warning'); return; }
  pullController = new AbortController();
  pullErrorMessage = null;
  el('pull-wrap').classList.remove('hidden');
  el('pull-name').textContent = name;
  el('pull-status').textContent = '시작 중...';
  el('pull-bytes').textContent = '';
  el('pull-progress').value = 0;

  try {
    const resp = await apiFetch(MODELS_API + '/pull', {
      method: 'POST',
      body: JSON.stringify({ name: name }),
      signal: pullController.signal,
    });
    if (!resp.ok) {
      const data = await resp.json();
      throw new Error(data.error || 'HTTP ' + resp.status);
    }
    const reader = resp.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';
    while (true) {
      const chunk = await reader.read();
      if (chunk.done) break;
      buffer += decoder.decode(chunk.value, { stream: true });
      const lines = buffer.split('\n');
      buffer = lines.pop();
      lines.filter(Boolean).forEach(function (line) {
        try { handlePullLine(JSON.parse(line)); } catch (e) { /* 불완전 라인 무시 */ }
      });
    }
    if (pullErrorMessage) {
      showToast('다운로드 실패: ' + pullErrorMessage
        + ' — 이 레포는 Ollama 직접 가져오기를 지원하지 않는 구조일 수 있습니다', 'error');
    } else {
      showToast(name + ' 다운로드 완료', 'success');
    }
  } catch (e) {
    if (e.name === 'AbortError') {
      showToast('다운로드를 취소했습니다. 다시 받으면 이어서 받습니다.', 'info');
    } else if (e.message.indexOf('Unauthorized') === -1) {
      showToast('다운로드 실패: ' + e.message, 'error');
    }
  } finally {
    pullController = null;
    el('pull-wrap').classList.add('hidden');
    loadInstalled();
  }
}

function handlePullLine(p) {
  if (p.error) { pullErrorMessage = p.error; return; }
  el('pull-status').textContent = p.status || '';
  if (p.total) {
    const percent = p.completed ? Math.round((p.completed / p.total) * 100) : 0;
    el('pull-progress').value = percent;
    el('pull-bytes').textContent = fmtSize(p.completed || 0) + ' / ' + fmtSize(p.total) + ' (' + percent + '%)';
  }
}

function cancelPull() {
  if (pullController) pullController.abort();
}

/* ---------- 테스트·벤치마크 ---------- */
function hasImageInput() {
  return !!(el('bench-file').files.length || el('bench-url').value.trim());
}

function renderBenchModels() {
  const wrap = el('bench-models');
  const checked = new Set(Array.from(wrap.querySelectorAll('input:checked')).map(function (c) { return c.value; }));
  if (!installedModels.length) {
    wrap.innerHTML = '<span class="text-sm opacity-60">설치된 모델이 없습니다</span>';
    return;
  }
  const imageMode = hasImageInput();
  wrap.innerHTML = installedModels.map(function (m) {
    const disabled = imageMode && !m.vision;
    return '<label class="label cursor-pointer gap-2 border border-base-300 rounded-lg px-3 py-1'
      + (disabled ? ' opacity-40' : '') + '">'
      + '<input type="checkbox" class="checkbox checkbox-sm" value="' + escapeHtml(m.name) + '"'
      + (disabled ? ' disabled' : '') + (!disabled && checked.has(m.name) ? ' checked' : '') + '>'
      + '<span class="font-mono text-sm">' + escapeHtml(m.name) + '</span>'
      + (m.vision ? '<span class="badge badge-info badge-xs">vision</span>' : '')
      + '</label>';
  }).join('');
}

function fileToBase64(file) {
  return new Promise(function (resolve, reject) {
    const reader = new FileReader();
    reader.onload = function () { resolve(String(reader.result).split(',')[1]); };
    reader.onerror = reject;
    reader.readAsDataURL(file);
  });
}

async function runBenchmark() {
  if (benchRunning) return;
  const prompt = el('bench-prompt').value.trim();
  if (!prompt) { showToast('프롬프트를 입력하세요', 'warning'); return; }
  const selected = Array.from(el('bench-models').querySelectorAll('input:checked'))
    .map(function (c) { return c.value; });
  if (!selected.length) { showToast('모델을 하나 이상 선택하세요', 'warning'); return; }

  let imageBase64 = null;
  const imageUrl = el('bench-url').value.trim();
  if (el('bench-file').files.length) {
    imageBase64 = await fileToBase64(el('bench-file').files[0]);
  }

  benchRunning = true;
  el('bench-run').disabled = true;
  el('bench-status').classList.remove('hidden');
  const empty = el('bench-empty');
  if (empty) empty.remove();

  /* 모델을 한 번에 하나씩 순차 실행 — 동시 로드로 인한 서버 메모리 폭주 방지 */
  for (const name of selected) {
    el('bench-current').textContent = name;
    const row = addBenchRow(name);
    const startedAt = performance.now();
    try {
      let resultText;
      let durationMs;
      if (imageBase64) {
        const resp = await apiFetch('../ocr/base64', {
          method: 'POST',
          body: JSON.stringify({ image_base64: imageBase64, prompt: prompt, model: name }),
        });
        const data = await resp.json();
        if (!resp.ok) throw new Error(data.error || 'HTTP ' + resp.status);
        resultText = data.result;
        durationMs = performance.now() - startedAt;
      } else if (imageUrl) {
        const resp = await apiFetch('../ocr/url', {
          method: 'POST',
          body: JSON.stringify({ image_url: imageUrl, prompt: prompt, model: name }),
        });
        const data = await resp.json();
        if (!resp.ok) throw new Error(data.error || 'HTTP ' + resp.status);
        resultText = data.result;
        durationMs = performance.now() - startedAt;
      } else {
        const resp = await apiFetch('../ollama/chat', {
          method: 'POST',
          body: JSON.stringify({ model: name, prompt: prompt }),
        });
        const data = await resp.json();
        if (!resp.ok) throw new Error(data.error || 'HTTP ' + resp.status);
        resultText = data.content;
        durationMs = (data.metrics && data.metrics.total_duration_ms) || (performance.now() - startedAt);
      }
      finishBenchRow(row, true, durationMs, resultText);
    } catch (e) {
      if (e.message.indexOf('Unauthorized') !== -1) { finishBenchRow(row, false, 0, '인증 필요'); break; }
      /* 한 모델 실패해도 다음 모델 계속 */
      finishBenchRow(row, false, performance.now() - startedAt, e.message);
    }
  }

  benchRunning = false;
  el('bench-run').disabled = false;
  el('bench-status').classList.add('hidden');
}

function addBenchRow(name) {
  const row = document.createElement('tr');
  row.innerHTML = '<td class="font-mono">' + escapeHtml(name) + '</td>'
    + '<td><span class="loading loading-spinner loading-xs"></span></td>'
    + '<td>-</td><td class="opacity-60">실행 중...</td>';
  el('bench-body').prepend(row);
  return row;
}

function finishBenchRow(row, ok, durationMs, text) {
  const cells = row.querySelectorAll('td');
  cells[1].innerHTML = ok
    ? '<span class="badge badge-success badge-sm">성공</span>'
    : '<span class="badge badge-error badge-sm">실패</span>';
  cells[2].textContent = (durationMs / 1000).toFixed(1) + 's';
  cells[3].innerHTML = '<pre class="text-xs whitespace-pre-wrap max-w-xl'
    + (ok ? '' : ' text-error') + '">' + escapeHtml(text || '') + '</pre>';
}

/* ---------- 초기화 ---------- */
document.addEventListener('DOMContentLoaded', function () {
  loadInstalled();
  el('installed-refresh').addEventListener('click', loadInstalled);
  el('search-btn').addEventListener('click', searchHf);
  el('search-input').addEventListener('keydown', function (e) { if (e.key === 'Enter') searchHf(); });
  el('pull-cancel').addEventListener('click', cancelPull);
  el('delete-confirm').addEventListener('click', doDelete);
  el('bench-run').addEventListener('click', runBenchmark);
  el('bench-file').addEventListener('change', renderBenchModels);
  el('bench-url').addEventListener('input', renderBenchModels);
});
