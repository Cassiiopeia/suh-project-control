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
    loadVoices(); // 엔진 실행 상태에 따라 미리듣기 버튼 활성화가 달라진다
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
          <button class="btn btn-ghost btn-xs ${engines.some(e => e.id === v.engine && e.status === 'running') ? '' : 'btn-disabled opacity-40'}"
                  onclick="previewVoice('${escapeHtml(v.id)}','${escapeHtml(v.engine)}')" title="미리듣기 (엔진 실행 중일 때)">
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
  // 해당 보이스의 엔진이 실행 중이 아니면 호출하지 않고 안내 (실측: 중지 엔진 미리듣기 503)
  const eng = engines.find(e => e.id === engine);
  if (!eng || eng.status !== 'running') {
    showToast(`${eng ? eng.name : engine} 엔진이 실행 중이 아닙니다 — 시작 후 미리듣기할 수 있어요`, 'warning');
    return;
  }
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

/* ---------- 브라우저 녹음 (마이크 → PCM16 WAV 변환 → 기존 등록 API 재사용) ---------- */

let mediaRecorder = null;   // 녹음 중이면 MediaRecorder 인스턴스
let recordedWav = null;     // 녹음 결과 WAV Blob — 파일 미선택 시 등록에 사용
let recordTimer = null;
let recordStartedAt = 0;

function encodeWav(samples, sampleRate) {
  /* Float32 PCM → 16bit mono WAV (서버가 RIFF 헤더를 검증하므로 WAV로 변환 필수) */
  const buf = new ArrayBuffer(44 + samples.length * 2);
  const v = new DataView(buf);
  const writeStr = (off, s) => { for (let i = 0; i < s.length; i++) v.setUint8(off + i, s.charCodeAt(i)); };
  writeStr(0, 'RIFF'); v.setUint32(4, 36 + samples.length * 2, true); writeStr(8, 'WAVE');
  writeStr(12, 'fmt '); v.setUint32(16, 16, true); v.setUint16(20, 1, true); v.setUint16(22, 1, true);
  v.setUint32(24, sampleRate, true); v.setUint32(28, sampleRate * 2, true);
  v.setUint16(32, 2, true); v.setUint16(34, 16, true);
  writeStr(36, 'data'); v.setUint32(40, samples.length * 2, true);
  for (let i = 0; i < samples.length; i++) {
    const s = Math.max(-1, Math.min(1, samples[i]));
    v.setInt16(44 + i * 2, s < 0 ? s * 0x8000 : s * 0x7FFF, true);
  }
  return new Blob([buf], { type: 'audio/wav' });
}

async function blobToWav(blob) {
  /* MediaRecorder 출력(webm/opus 등) → 디코딩 → 모노 WAV */
  const ctx = new (window.AudioContext || window.webkitAudioContext)();
  try {
    const audio = await ctx.decodeAudioData(await blob.arrayBuffer());
    let mono = audio.getChannelData(0);
    if (audio.numberOfChannels > 1) {
      const ch2 = audio.getChannelData(1);
      mono = mono.map((s, i) => (s + ch2[i]) / 2);
    }
    return encodeWav(mono, audio.sampleRate);
  } finally {
    ctx.close();
  }
}

function setRecordUi(recording) {
  el('voice-record-label').textContent = recording ? '중지' : '녹음';
  el('voice-record').classList.toggle('btn-error', recording);
  el('voice-record-status').classList.toggle('hidden', !recording);
}

el('voice-record').addEventListener('click', async () => {
  if (mediaRecorder && mediaRecorder.state === 'recording') {
    mediaRecorder.stop();
    return;
  }
  let stream;
  try {
    stream = await navigator.mediaDevices.getUserMedia({ audio: true });
  } catch (e) {
    showToast('마이크 권한이 필요합니다: ' + e.message, 'error');
    return;
  }
  const chunks = [];
  mediaRecorder = new MediaRecorder(stream);
  mediaRecorder.ondataavailable = e => chunks.push(e.data);
  mediaRecorder.onstop = async () => {
    stream.getTracks().forEach(t => t.stop());
    clearInterval(recordTimer);
    setRecordUi(false);
    try {
      recordedWav = await blobToWav(new Blob(chunks));
      el('voice-record-preview').classList.remove('hidden');
      el('voice-record-audio').src = URL.createObjectURL(recordedWav);
      showToast('녹음 완료 — 미리듣기 후 등록하세요', 'success');
    } catch (e) {
      showToast('녹음 변환 실패: ' + e.message, 'error');
    }
  };
  mediaRecorder.start();
  recordStartedAt = Date.now();
  setRecordUi(true);
  recordTimer = setInterval(() => {
    const sec = ((Date.now() - recordStartedAt) / 1000).toFixed(0);
    el('voice-record-status').textContent = `녹음 중... ${sec}초 (3~30초 권장)`;
  }, 500);
});

el('voice-record-discard').addEventListener('click', () => {
  recordedWav = null;
  el('voice-record-preview').classList.add('hidden');
});

let droppedFile = null;  // 드래그&드랍으로 받은 파일 (파일 선택보다 우선순위 낮음)

// 카드 전체를 드랍 영역으로 — 어떤 오디오든 받는다 (업로드 시 WAV로 자동 변환)
const voiceCard = el('voice-card');
['dragover', 'dragenter'].forEach(ev => voiceCard.addEventListener(ev, e => {
  e.preventDefault();
  voiceCard.classList.add('ring', 'ring-primary');
}));
['dragleave', 'drop'].forEach(ev => voiceCard.addEventListener(ev, e => {
  e.preventDefault();
  voiceCard.classList.remove('ring', 'ring-primary');
}));
voiceCard.addEventListener('drop', e => {
  const f = e.dataTransfer.files && e.dataTransfer.files[0];
  if (!f) return;
  droppedFile = f;
  showToast(`파일 준비됨: ${f.name} — 이름 입력 후 등록을 누르세요`, 'info');
});

async function toUploadWav(file) {
  /* m4a/mp3 등 브라우저가 디코딩 가능한 모든 오디오를 서버가 받는 PCM16 WAV로 변환.
     이미 WAV여도 float32 등 변형이 있어 항상 재인코딩한다 */
  try {
    return await blobToWav(file);
  } catch (e) {
    throw new Error('오디오 변환 실패 — 파일 형식을 확인하세요 (' + e.message + ')');
  }
}

el('voice-upload').addEventListener('click', async () => {
  const name = el('voice-name').value.trim();
  // 우선순위: 파일 선택 > 드래그&드랍 > 브라우저 녹음
  const source = el('voice-file').files[0] || droppedFile
    || (recordedWav && new File([recordedWav], 'recorded.wav', { type: 'audio/wav' }));
  if (!name) { showToast('보이스 이름을 입력하세요', 'warning'); return; }
  if (!source) { showToast('음성 파일을 선택/드랍하거나 녹음하세요', 'warning'); return; }
  const btn = el('voice-upload');
  btn.disabled = true;
  try {
    const wavBlob = await toUploadWav(source);
    const form = new FormData();
    form.append('name', name);
    form.append('file', new File([wavBlob], 'voice.wav', { type: 'audio/wav' }));
    const resp = await fetch(TTS_API + '/voices', {
      method: 'POST', headers: { 'X-API-Key': apiKey() }, body: form,
    });
    // 게이트웨이(413/524 등)가 HTML을 돌려주는 경우 대비 — JSON 파싱 실패를 친절하게
    let data;
    try {
      data = await resp.json();
    } catch (e) {
      throw new Error(`업로드 실패 (HTTP ${resp.status}) — 파일이 크거나 서버 제한에 걸렸습니다`);
    }
    if (!resp.ok) throw new Error(data.error || '등록 실패');
    showToast(`보이스 등록 완료: ${data.voice.id}`, 'success');
    el('voice-name').value = '';
    el('voice-file').value = '';
    droppedFile = null;
    recordedWav = null;
    el('voice-record-preview').classList.add('hidden');
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
