/* 모델 관리 페이지 로직. base: /admin/models → API는 ../models/*, ../ollama/*, ../ocr/* */
const MODELS_API = '../models';

let installedModels = [];   // GET /models/installed 결과 캐시
let queuePollTimer = null;  // 큐 폴링 타이머 — 대기/진행 항목이 있을 때만 동작
let queueSnapshot = [];     // 직전 폴링 결과 (완료 전이 감지용)
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
      btn.addEventListener('click', function () { enqueuePull(btn.dataset.pull); });
    });
  } catch (e) {
    body.innerHTML = '<tr><td colspan="4" class="text-center text-error">' + escapeHtml(e.message) + '</td></tr>';
  }
}

/* ---------- 다운로드 큐 ---------- */
async function enqueuePull(name) {
  try {
    const resp = await apiFetch(MODELS_API + '/queue', {
      method: 'POST',
      body: JSON.stringify({ name: name }),
    });
    const data = await resp.json();
    if (!resp.ok) throw new Error(data.error || 'HTTP ' + resp.status);
    showToast(name + ' 큐에 추가했습니다', 'success');
    queueSnapshot = data.queue;
    renderQueue(data.queue);
    startQueuePolling();
  } catch (e) {
    if (e.message.indexOf('Unauthorized') === -1) {
      showToast('큐 추가 실패: ' + e.message, 'error');
    }
  }
}

function startQueuePolling() {
  if (queuePollTimer) return;
  queuePollTimer = setInterval(pollQueue, 1500);
}

function stopQueuePolling() {
  if (queuePollTimer) { clearInterval(queuePollTimer); queuePollTimer = null; }
}

async function pollQueue() {
  try {
    const resp = await apiFetch(MODELS_API + '/queue');
    const data = await resp.json();
    if (!resp.ok) throw new Error(data.error || '큐 조회 실패');
    notifyFinished(queueSnapshot, data.queue);
    queueSnapshot = data.queue;
    renderQueue(data.queue);
    const active = data.queue.some(function (i) {
      return i.status === 'queued' || i.status === 'pulling';
    });
    if (active) startQueuePolling(); else stopQueuePolling();
  } catch (e) {
    stopQueuePolling(); // 인증 만료 등 — 다음 사용자 조작에서 재개
  }
}

/* 직전 폴링과 비교해 이번에 끝난 항목을 토스트로 알리고 설치 목록을 갱신 */
function notifyFinished(prev, next) {
  const wasActive = {};
  prev.forEach(function (i) {
    if (i.status === 'queued' || i.status === 'pulling') wasActive[i.id] = true;
  });
  let anyDone = false;
  next.forEach(function (i) {
    if (!wasActive[i.id]) return;
    if (i.status === 'done') {
      showToast(i.name + ' 다운로드 완료', 'success');
      anyDone = true;
    } else if (i.status === 'error') {
      showToast(i.name + ' 다운로드 실패: ' + (i.error || '')
        + ' — 이 레포는 Ollama 직접 가져오기를 지원하지 않는 구조일 수 있습니다', 'error');
    } else if (i.status === 'canceled') {
      showToast(i.name + ' 다운로드를 취소했습니다. 다시 받으면 이어서 받습니다.', 'info');
    }
  });
  if (anyDone) loadInstalled();
}

const QUEUE_BADGE = {
  queued: ['badge-ghost', '대기'],
  pulling: ['badge-info', '다운로드 중'],
  done: ['badge-success', '완료'],
  error: ['badge-error', '실패'],
  canceled: ['badge-warning', '취소'],
};

function renderQueue(items) {
  const wrap = el('queue-wrap');
  const body = el('queue-body');
  if (!items.length) { wrap.classList.add('hidden'); return; }
  wrap.classList.remove('hidden');
  body.innerHTML = items.map(function (i) {
    const badge = QUEUE_BADGE[i.status] || ['badge-ghost', i.status];
    let html = '<div class="border border-base-300 rounded-lg p-2 space-y-1">'
      + '<div class="flex items-center justify-between gap-2">'
      + '<span class="text-sm font-mono break-all">' + escapeHtml(i.name) + '</span>'
      + '<span class="flex items-center gap-2 shrink-0">'
      + '<span class="badge badge-sm ' + badge[0] + '">' + badge[1] + '</span>';
    if (i.status === 'queued' || i.status === 'pulling') {
      html += '<button class="btn btn-error btn-xs" data-qcancel="' + escapeHtml(i.id) + '">'
        + (i.status === 'queued' ? '제거' : '취소') + '</button>';
    }
    html += '</span></div>';
    if (i.status === 'pulling') {
      const percent = (i.total && i.completed) ? Math.round((i.completed / i.total) * 100) : 0;
      html += '<progress class="progress progress-primary w-full" value="' + percent + '" max="100"></progress>'
        + '<div class="text-xs opacity-70 text-right">'
        + fmtSize(i.completed || 0) + ' / ' + fmtSize(i.total || 0) + ' (' + percent + '%)</div>';
    } else if (i.status === 'error' && i.error) {
      html += '<div class="text-xs text-error">' + escapeHtml(i.error) + '</div>';
    }
    return html + '</div>';
  }).join('');
  body.querySelectorAll('[data-qcancel]').forEach(function (btn) {
    btn.addEventListener('click', function () { cancelQueueItem(btn.dataset.qcancel); });
  });
}

async function cancelQueueItem(itemId) {
  try {
    const resp = await apiFetch(MODELS_API + '/queue/' + encodeURIComponent(itemId), { method: 'DELETE' });
    const data = await resp.json();
    if (!resp.ok) throw new Error(data.error || '취소 실패');
    pollQueue(); // 즉시 갱신 — 다음 폴링 주기를 기다리지 않음
  } catch (e) {
    if (e.message.indexOf('Unauthorized') === -1) {
      showToast('취소 실패: ' + e.message, 'error');
    }
  }
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
  pollQueue(); // 새로고침해도 진행 중인 큐 상태 복원 — 활성 항목 있으면 폴링 자동 시작
  el('installed-refresh').addEventListener('click', loadInstalled);
  el('search-btn').addEventListener('click', searchHf);
  el('search-input').addEventListener('keydown', function (e) { if (e.key === 'Enter') searchHf(); });
  el('delete-confirm').addEventListener('click', doDelete);
  el('bench-run').addEventListener('click', runBenchmark);
  el('bench-file').addEventListener('change', renderBenchModels);
  el('bench-url').addEventListener('input', renderBenchModels);
});
