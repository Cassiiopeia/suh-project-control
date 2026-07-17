/* TTS 관리 페이지 로직. base: /admin/tts → API는 ../tts/* */
const TTS_API = '../tts';

let engines = [];        // 최신 엔진 상태 캐시
let pollTimer = null;    // 상태 폴링 (installing/starting이 있으면 짧게)
let logsTarget = null;   // 로그 모달이 보고 있는 엔진 id
let logsTimer = null;

function el(id) { return document.getElementById(id); }

const STATUS_BADGE = {
  not_installed: ['미설치', 'badge-ghost'],
  installing: ['설치 중...', 'badge-warning'],
  stopped: ['중지됨', 'badge-neutral'],
  starting: ['기동 중 (모델 로딩)', 'badge-warning'],
  running: ['실행 중', 'badge-success'],
  error: ['오류', 'badge-error'],
};

/* ---------- 엔진 카드 ---------- */

async function loadEngines() {
  try {
    const resp = await apiFetch(TTS_API + '/engines');
    const data = await resp.json();
    if (!resp.ok) throw new Error(data.error || '조회 실패');
    engines = data.engines;
    el('engines-error').classList.add('hidden');
    renderEngines();
    renderTestPanel();
  } catch (e) {
    el('engines-error').classList.remove('hidden');
    el('engines-error').querySelector('span').textContent = e.message;
  }
  schedulePoll();
}

function schedulePoll() {
  clearTimeout(pollTimer);
  // 전이 상태(설치/기동 중)가 있으면 3초, 아니면 10초 간격
  const busy = engines.some(e => ['installing', 'starting'].includes(e.status));
  pollTimer = setTimeout(loadEngines, busy ? 3000 : 10000);
}

function renderEngines() {
  el('engine-cards').innerHTML = engines.map(e => {
    const [label, badge] = STATUS_BADGE[e.status] || [e.status, 'badge-ghost'];
    const buttons = [];
    if (e.status === 'not_installed' || e.status === 'error') {
      buttons.push(`<button class="btn btn-sm btn-primary" onclick="controlEngine('${e.id}','install')">설치</button>`);
    }
    if (e.status === 'stopped') {
      buttons.push(`<button class="btn btn-sm btn-primary" onclick="startEngine('${e.id}')">시작</button>`);
    }
    if (e.status === 'running' || e.status === 'starting') {
      buttons.push(`<button class="btn btn-sm" onclick="controlEngine('${e.id}','stop')">중지</button>`);
    }
    if (e.status !== 'not_installed') {
      buttons.push(`<button class="btn btn-sm btn-ghost" onclick="showLogs('${e.id}')">로그</button>`);
    }
    const installError = e.install_error
      ? `<div class="text-error text-xs mt-1">${escapeHtml(e.install_error)}</div>` : '';
    // 설치(pull) 진행 상황 — 3초 폴링으로 갱신된다
    const installProgress = e.status === 'installing'
      ? `<div class="text-xs opacity-70 font-mono truncate mt-1">${escapeHtml(e.install_progress || '이미지 다운로드 준비 중...')}</div>` : '';
    return `
      <div class="border border-base-300 rounded-lg p-4 space-y-2">
        <div class="flex items-center justify-between">
          <span class="font-semibold">${escapeHtml(e.name)}</span>
          <span class="badge badge-sm ${badge}">${label}</span>
        </div>
        <p class="text-xs opacity-70">${escapeHtml(e.description)}</p>
        <div class="text-xs opacity-60">언어: ${e.languages.join(', ')} · VRAM: ${escapeHtml(e.vram)}</div>
        ${installProgress}
        ${installError}
        <div class="flex gap-2 pt-1">${buttons.join('')}</div>
      </div>`;
  }).join('');
}

async function controlEngine(id, action) {
  try {
    const resp = await apiFetch(`${TTS_API}/engines/${id}/${action}`, { method: 'POST' });
    const data = await resp.json();
    if (!resp.ok) throw new Error(data.error || action + ' 실패');
    engines = data.engines;
    renderEngines();
    renderTestPanel();
    schedulePoll();
  } catch (e) {
    showToast(e.message, 'error');
  }
}

function startEngine(id) {
  // 1개만 실행 정책 — 다른 엔진이 실행/기동 중이면 전환 확인
  const other = engines.find(e => e.id !== id && ['running', 'starting'].includes(e.status));
  if (other && !confirm(`${other.name}을(를) 중지하고 전환할까요?`)) return;
  controlEngine(id, 'start');
}

/* ---------- 로그 모달 ---------- */

async function refreshLogs() {
  if (!logsTarget) return;
  try {
    const resp = await apiFetch(`${TTS_API}/engines/${logsTarget}/logs`);
    const data = await resp.json();
    el('logs-body').textContent = resp.ok ? data.logs : (data.error || '로그 조회 실패');
  } catch (e) {
    el('logs-body').textContent = e.message;
  }
  logsTimer = setTimeout(refreshLogs, 3000);
}

function showLogs(id) {
  logsTarget = id;
  el('logs-title').textContent = `컨테이너 로그 — ${id}`;
  el('logs-body').textContent = '불러오는 중...';
  el('logs-modal').showModal();
  clearTimeout(logsTimer);
  refreshLogs();
}

el('logs-modal').addEventListener('close', () => {
  logsTarget = null;
  clearTimeout(logsTimer);
});

/* ---------- 합성 테스트 ---------- */

function renderTestPanel() {
  const running = engines.find(e => e.status === 'running');
  const badge = el('test-engine-badge');
  const select = el('tts-voice');
  if (!running) {
    badge.textContent = '실행 중 엔진 없음';
    badge.className = 'badge badge-ghost badge-sm';
    select.innerHTML = '<option>-</option>';
    el('tts-run').disabled = true;
    return;
  }
  badge.textContent = running.name;
  badge.className = 'badge badge-success badge-sm';
  el('tts-run').disabled = false;
  // 실행 엔진이 바뀌었을 때만 보이스 목록 재구성 (선택 유지)
  if (select.dataset.engine !== running.id) {
    select.dataset.engine = running.id;
    select.innerHTML = running.voices.map(v =>
      `<option value="${escapeHtml(v.id)}">${escapeHtml(v.name)}</option>`).join('');
  }
}

el('tts-speed').addEventListener('input', () => {
  el('speed-value').textContent = Number(el('tts-speed').value).toFixed(1);
});

el('tts-run').addEventListener('click', async () => {
  const text = el('tts-text').value.trim();
  if (!text) { showToast('텍스트를 입력하세요', 'warning'); return; }
  const btn = el('tts-run');
  btn.disabled = true;
  btn.innerHTML = '<span class="loading loading-spinner loading-xs"></span>합성 중...';
  try {
    const resp = await apiFetch(TTS_API, {
      method: 'POST',
      body: JSON.stringify({
        text,
        voice: el('tts-voice').value,
        speed: Number(el('tts-speed').value),
      }),
    });
    if (!resp.ok) {
      const data = await resp.json();
      throw new Error(data.error || '합성 실패');
    }
    const url = URL.createObjectURL(await resp.blob());
    el('tts-result').classList.remove('hidden');
    el('tts-audio').src = url;
    el('tts-download').href = url;
    el('tts-audio').play();
  } catch (e) {
    showToast(e.message, 'error');
  } finally {
    btn.disabled = false;
    btn.innerHTML = '<i data-lucide="play" class="size-4"></i>합성';
    if (window.lucide) lucide.createIcons();
  }
});

/* ---------- 보이스 관리 ---------- */

// multipart 업로드는 apiFetch(항상 JSON Content-Type)를 못 쓴다 — 키만 직접 붙인다
function apiKey() { return localStorage.getItem('suh_admin_api_key') || ''; }

async function loadVoices() {
  const body = el('voice-body');
  try {
    const resp = await apiFetch(TTS_API + '/voices');
    const data = await resp.json();
    if (!resp.ok) throw new Error(data.error || '조회 실패');
    body.innerHTML = data.voices.map(v => `
      <tr>
        <td>${escapeHtml(v.name)}</td>
        <td class="font-mono text-xs">${escapeHtml(v.id)}</td>
        <td><span class="badge badge-sm ${v.builtin ? 'badge-ghost' : 'badge-primary'}">${v.builtin ? '내장' : '사용자'}</span>
            <span class="badge badge-sm badge-ghost">${escapeHtml(v.engine)}</span></td>
        <td class="text-xs opacity-70">${escapeHtml(v.created_at || '-')}</td>
        <td class="flex gap-1">
          <button class="btn btn-ghost btn-xs" onclick="previewVoice('${escapeHtml(v.id)}','${escapeHtml(v.engine)}')" title="미리듣기">
            <i data-lucide="play" class="size-3"></i>
          </button>
          ${v.builtin ? '' : `<button class="btn btn-ghost btn-xs text-error" onclick="deleteVoice('${escapeHtml(v.id)}')" title="삭제">
            <i data-lucide="trash-2" class="size-3"></i>
          </button>`}
        </td>
      </tr>`).join('');
    if (window.lucide) lucide.createIcons();
  } catch (e) {
    body.innerHTML = `<tr><td colspan="5" class="text-error text-xs">${escapeHtml(e.message)}</td></tr>`;
  }
}

async function previewVoice(id, engine) {
  try {
    const resp = await apiFetch(TTS_API, {
      method: 'POST',
      body: JSON.stringify({
        text: engine === 'kokoro' ? 'Hello, this is a voice preview.' : '안녕하세요, 보이스 미리듣기입니다.',
        engine, voice: id,
      }),
    });
    if (!resp.ok) {
      const data = await resp.json();
      throw new Error(data.error || '미리듣기 실패');
    }
    new Audio(URL.createObjectURL(await resp.blob())).play();
  } catch (e) {
    showToast(e.message, 'error');
  }
}

async function deleteVoice(id) {
  if (!confirm(`보이스 ${id}를 삭제할까요?`)) return;
  try {
    const resp = await apiFetch(`${TTS_API}/voices/${id}`, { method: 'DELETE' });
    const data = await resp.json();
    if (!resp.ok) throw new Error(data.error || '삭제 실패');
    showToast('삭제되었습니다', 'success');
    loadVoices();
    loadEngines(); // 테스트 패널 보이스 목록도 갱신
  } catch (e) {
    showToast(e.message, 'error');
  }
}

el('voice-upload').addEventListener('click', async () => {
  const name = el('voice-name').value.trim();
  const file = el('voice-file').files[0];
  if (!name) { showToast('보이스 이름을 입력하세요', 'warning'); return; }
  if (!file) { showToast('음성 파일(WAV)을 선택하세요', 'warning'); return; }
  const form = new FormData();
  form.append('name', name);
  form.append('file', file);
  const btn = el('voice-upload');
  btn.disabled = true;
  try {
    const resp = await fetch(TTS_API + '/voices', {
      method: 'POST', headers: { 'X-API-Key': apiKey() }, body: form,
    });
    const data = await resp.json();
    if (!resp.ok) throw new Error(data.error || '등록 실패');
    showToast(`보이스 등록 완료: ${data.voice.id}`, 'success');
    el('voice-name').value = '';
    el('voice-file').value = '';
    loadVoices();
    loadEngines();
  } catch (e) {
    showToast(e.message, 'error');
  } finally {
    btn.disabled = false;
  }
});

loadEngines();
loadVoices();
