/* 팰월드 관리 페이지 로직. base: /admin/palworld → API는 ../palworld/* */
const API = '../palworld';
let currentState = 'unknown';

const ALL_CROSSPLAY_PLATFORMS = '(Steam,Xbox,PS5,Mac)';
const STEAM_ONLY_PLATFORM = '(Steam)';
const SETTINGS_FIELDS = [
  { key: 'ServerName', label: '서버 이름', type: 'text', defaultValue: '', recommended: '팰 사냥터',
    description: '서버 목록에 표시될 이름' },
  { key: 'ServerDescription', label: '서버 설명', type: 'text', defaultValue: '', recommended: null,
    placeholder: '서버 소개를 입력하세요', description: '서버 목록에 표시될 간단한 소개' },
  { key: 'ServerPassword', label: '접속 비밀번호', type: 'text', defaultValue: '', recommended: '1234',
    placeholder: '비어 있으면 공개 서버', description: '빈 값이면 누구나 접속할 수 있는 공개 서버' },
  { key: 'ServerPlayerMaxNum', label: '최대 접속 인원', type: 'number', defaultValue: '32', recommended: '32',
    min: '1', max: '32', step: '1', recommendedLabel: '인원에 맞게 (최대 32)', description: '서버에 동시에 접속할 수 있는 최대 인원' },
  { key: 'CrossplayPlatforms', displayKey: 'bCrossplay → CrossplayPlatforms', label: '크로스플레이', type: 'crossplay',
    defaultValue: STEAM_ONLY_PLATFORM, recommended: ALL_CROSSPLAY_PLATFORMS,
    recommendedLabel: 'True (Steam · Xbox · PS5 · Mac)', defaultLabel: 'False (Steam 전용)',
    description: '최신 서버 설정 키를 사용해 모든 플랫폼의 접속을 허용' },
  { key: 'ExpRate', label: '경험치 배율', type: 'number', defaultValue: '1.0', recommended: '2.0',
    min: '0.1', step: '0.1', recommendedLabel: '2.0 ~ 3.0', description: '플레이어와 팰이 얻는 경험치 배율' },
  { key: 'PalCaptureRate', label: '팰 포획 배율', type: 'number', defaultValue: '1.0', recommended: '2.0',
    min: '0.1', step: '0.1', description: '팰 포획 성공 확률에 적용되는 배율' },
  { key: 'DeathPenalty', label: '사망 페널티', type: 'select', defaultValue: 'All', recommended: 'Item',
    recommendedLabel: 'None 또는 Item', options: [
      ['None', '없음'], ['Item', '장비 외 아이템'], ['ItemAndEquipment', '아이템과 장비'], ['All', '아이템·장비·보유 팰'],
    ], description: '캐릭터 사망 시 떨어뜨리는 대상' },
  { key: 'bEnablePlayerToPlayerDamage', label: '플레이어 간 피해 (PvP)', type: 'boolean', defaultValue: 'False', recommended: 'False',
    description: '다른 플레이어에게 피해를 줄 수 있는지 여부' },
  { key: 'DayTimeSpeedRate', label: '낮 시간 속도', type: 'number', defaultValue: '1.0', recommended: null,
    min: '0.1', step: '0.1', description: '낮 시간이 흐르는 속도' },
  { key: 'NightTimeSpeedRate', label: '밤 시간 속도', type: 'number', defaultValue: '1.0', recommended: null,
    min: '0.1', step: '0.1', description: '밤 시간이 흐르는 속도' },
  { key: 'PalSpawnNumRate', label: '팰 출현 배율', type: 'number', defaultValue: '1.0', recommended: null,
    min: '0.1', step: '0.1', description: '필드에 등장하는 팰의 수 (높을수록 서버 부하 증가)' },
  { key: 'CollectionDropRate', label: '채집 드롭 배율', type: 'number', defaultValue: '1.0', recommended: null,
    min: '0.1', step: '0.1', description: '채집 오브젝트에서 얻는 아이템 배율' },
  { key: 'WorkSpeedRate', label: '작업 속도 배율', type: 'number', defaultValue: '1.0', recommended: null,
    min: '0.1', step: '0.1', description: '거점 작업 속도에 적용되는 배율' },
];

function setText(id, value) {
  const el = document.getElementById(id);
  if (el) el.textContent = value;
}

async function refreshStatus() {
  try {
    const resp = await apiFetch(API + '/status');
    const data = await resp.json();
    currentState = data.state;
    const badge = document.getElementById('state-badge');
    badge.textContent = data.state.toUpperCase();
    badge.className = 'badge ' + (data.state === 'running' ? 'badge-success' : 'badge-error');

    const m = data.metrics;
    if (data.rest_available && m) {
      setText('stat-players', m.currentplayernum);
      setText('stat-maxplayers', '/ ' + m.maxplayernum + ' 명');
      setText('stat-fps', m.serverfps);
      setText('stat-fpsavg', m.serverfpsaverage != null ? '평균 ' + Number(m.serverfpsaverage).toFixed(1) : '평균 -');
      setText('stat-frametime', m.serverframetime != null ? Number(m.serverframetime).toFixed(1) : '-');
      setText('stat-uptime', formatUptime(m.uptime));
      setText('stat-days', m.days != null ? m.days + '일' : '-');
      setText('stat-basecamp', m.basecampnum != null ? m.basecampnum : '-');
    } else {
      ['stat-players', 'stat-fps', 'stat-frametime', 'stat-uptime', 'stat-days', 'stat-basecamp'].forEach(id => setText(id, '-'));
      setText('stat-fpsavg', '평균 -');
    }
    if (data.info) setText('stat-version', data.info.version || '-');

    renderPlayers(data.players);
    renderWorldInfo(data);
  } catch (e) { /* 401은 modal 처리 */ }
}

function renderPlayers(players) {
  const tbody = document.getElementById('player-list');
  if (!tbody) return;
  if (players && players.length) {
    tbody.innerHTML = players.map(p => {
      const coord = (p.location_x != null && p.location_y != null)
        ? Math.round(p.location_x / 1000) + ', ' + Math.round(p.location_y / 1000) : '-';
      return '<tr>' +
        '<td>' + escapeHtml(p.name) + '</td>' +
        '<td>' + escapeHtml(p.accountName || '-') + '</td>' +
        '<td>' + escapeHtml(p.level) + '</td>' +
        '<td>' + (p.ping != null ? Math.round(p.ping) + 'ms' : '-') + '</td>' +
        '<td class="font-mono text-xs">' + escapeHtml(p.userId || '-') + '</td>' +
        '<td class="font-mono text-xs">' + escapeHtml(p.iP || p.ip || '-') + '</td>' +
        '<td class="font-mono text-xs">' + coord + '</td>' +
        '</tr>';
    }).join('');
  } else {
    tbody.innerHTML = '<tr><td colspan="7">접속자 없음</td></tr>';
  }
  document.getElementById('players-section')?.classList.toggle('hidden', !(players && players.length));
}

/* 월드/서버 정보 카드 — info + settings 요약 */
const WORLD_INFO_ROWS = [
  { label: '서버 이름', get: d => d.info && d.info.servername },
  { label: '서버 설명', get: d => d.info && d.info.description },
  { label: '게임 버전', get: d => d.info && d.info.version },
  { label: '월드 GUID', get: d => d.info && d.info.worldguid, mono: true },
  { label: '난이도', get: d => d.settings && d.settings.Difficulty },
  { label: '경험치 배율', get: d => d.settings && d.settings.ExpRate, suffix: '배' },
  { label: '팰 포획 배율', get: d => d.settings && d.settings.PalCaptureRate, suffix: '배' },
  { label: '자동 저장 주기', get: d => d.settings && d.settings.autoSaveSpan, suffix: '초' },
  { label: 'PvP', get: d => d.settings && (d.settings.bIsPvP ? '켜짐' : '꺼짐') },
  { label: '사망 페널티', get: d => d.settings && d.settings.DeathPenalty },
  { label: '크로스플레이', get: d => d.settings && Array.isArray(d.settings.CrossplayPlatforms) ? d.settings.CrossplayPlatforms.join(' · ') : null },
  { label: '최대 인원', get: d => d.settings && d.settings.ServerPlayerMaxNum, suffix: '명' },
];

function renderWorldInfo(data) {
  const box = document.getElementById('world-info');
  if (!box) return;
  if (!data.rest_available) {
    box.innerHTML = '<div class="opacity-60 col-span-full">서버 정지 중 — 정보를 불러올 수 없습니다.</div>';
    return;
  }
  // 라벨(고정폭, 좌측 muted) + 값(바로 옆 좌측정렬) 한 줄 key-value.
  // justify-between으로 양끝에 붙이지 않으므로 옆 칸 라벨과 겹치지 않는다.
  box.innerHTML = WORLD_INFO_ROWS.map(row => {
    let v = row.get(data);
    if (v == null || v === '') v = '-';
    else if (row.suffix) v = v + row.suffix;
    return '<div class="flex items-baseline gap-3 py-1.5 px-2 rounded odd:bg-base-200/40 min-w-0">' +
      '<span class="opacity-50 w-20 shrink-0">' + escapeHtml(row.label) + '</span>' +
      '<span class="min-w-0 break-words font-medium ' + (row.mono ? 'font-mono text-xs' : '') + '">' + escapeHtml(v) + '</span>' +
      '</div>';
  }).join('');
}

function formatUptime(seconds) {
  const h = Math.floor(seconds / 3600), m = Math.floor((seconds % 3600) / 60);
  return h + 'h ' + m + 'm';
}

/* 스파크라인 렌더러는 admin-common.js의 window.sparkline 공용 헬퍼를 사용한다 */

async function loadHistory() {
  try {
    const resp = await apiFetch(API + '/history?limit=120');
    const data = await resp.json();
    const points = data.points || [];
    if (!points.length) return;
    const fps = points.map(p => (typeof p.serverfps === 'number' ? p.serverfps : NaN));
    const players = points.map(p => (typeof p.currentplayernum === 'number' ? p.currentplayernum : NaN));
    sparkline('spark-fps', fps, { min: 0, max: 60, klass: 'text-success' });
    sparkline('spark-players', players, { min: 0, klass: 'text-primary' });
    const lastFps = [...fps].reverse().find(v => !isNaN(v));
    const lastP = [...players].reverse().find(v => !isNaN(v));
    setText('spark-fps-label', lastFps != null ? lastFps + ' fps' : '');
    setText('spark-players-label', lastP != null ? lastP + ' 명' : '');
  } catch (e) { /* ignore */ }
}

async function controlServer(action) {
  const labels = { start: '시작', stop: '중지', restart: '재시작' };
  if (!(await confirmAction('서버를 ' + labels[action] + ' 하시겠습니까?'))) return;
  try {
    const resp = await apiFetch(API + '/' + action, { method: 'POST' });
    const data = await resp.json();
    if (data.success) showToast(labels[action] + ' 완료', 'success');
    else showToast(data.error || labels[action] + ' 실패', 'error');
  } catch (e) {
    showToast(String(e), 'error');
  }
  setTimeout(refreshStatus, 2000);
}

async function loadSettings() {
  try {
    const resp = await apiFetch(API + '/settings');
    const data = await resp.json();
    const pending = data.pending || {};
    // 적용 대기 중인 값이 있으면 폼에는 그 값을 우선 보여준다 — 사용자가 방금 저장한
    // 값이 "사라진 것처럼" 보이지 않도록.
    const effectiveSettings = { ...data.settings, ...pending };
    const form = document.getElementById('settings-form');
    form.innerHTML = SETTINGS_FIELDS.map(field => renderSettingRow(field, effectiveSettings)).join('');
    form.querySelectorAll('input[type="checkbox"]').forEach(toggle => {
      toggle.addEventListener('change', updateToggleLabel);
      updateToggleLabel({ target: toggle });
    });
    const pendingCount = Object.keys(pending).length;
    document.getElementById('pending-count').textContent = pendingCount;
    document.getElementById('pending-alert').classList.toggle('hidden', pendingCount === 0);
  } catch (e) {
    showToast('설정을 불러오지 못했습니다: ' + String(e), 'error');
  }
}

function unquote(raw) {
  const value = String(raw == null ? '' : raw);
  return value.startsWith('"') && value.endsWith('"') ? value.slice(1, -1) : value;
}

function fieldValue(field, settings) {
  if (Object.prototype.hasOwnProperty.call(settings, field.key)) return unquote(settings[field.key]);
  // 구버전 설정 파일도 화면에서는 정상적으로 읽는다. 저장하면 최신 키로 마이그레이션된다.
  if (field.type === 'crossplay' && Object.prototype.hasOwnProperty.call(settings, 'bCrossplay')) {
    return settings.bCrossplay === 'True' ? ALL_CROSSPLAY_PLATFORMS : STEAM_ONLY_PLATFORM;
  }
  return field.defaultValue;
}

function renderSettingRow(field, settings) {
  const value = fieldValue(field, settings);
  const key = escapeHtml(field.key);
  let control;
  if (field.type === 'boolean' || field.type === 'crossplay') {
    const checked = field.type === 'crossplay' ? value !== STEAM_ONLY_PLATFORM : value === 'True';
    control = '<label class="setting-toggle"><input type="checkbox" class="toggle toggle-primary" data-key="' + key + '"' +
      (checked ? ' checked' : '') + '><span class="setting-toggle-state"></span></label>';
  } else if (field.type === 'select') {
    control = '<select class="select select-bordered select-sm setting-control" data-key="' + key + '">' +
      field.options.map(option => '<option value="' + escapeHtml(option[0]) + '"' + (value === option[0] ? ' selected' : '') + '>' +
        escapeHtml(option[0] + ' · ' + option[1]) + '</option>').join('') + '</select>';
  } else {
    const attrs = ['type="' + field.type + '"', 'class="input input-bordered input-sm setting-control"', 'data-key="' + key + '"',
      'value="' + escapeHtml(value) + '"'];
    ['min', 'max', 'step'].forEach(name => { if (field[name]) attrs.push(name + '="' + field[name] + '"'); });
    const placeholder = field.placeholder || (field.recommended != null ? '추천: ' + field.recommended : '');
    if (placeholder) attrs.push('placeholder="' + escapeHtml(placeholder) + '"');
    control = '<input ' + attrs.join(' ') + '>';
  }

  const defaultText = field.defaultLabel || (field.defaultValue === '' ? '빈 값' : field.defaultValue);
  const recommendedText = field.recommendedLabel || (field.recommended == null ? '현재값 유지' : field.recommended);
  return '<div class="setting-row">' +
    '<div class="setting-name"><span class="setting-label">' + escapeHtml(field.label) + '</span>' +
    '<span class="setting-key">' + escapeHtml(field.displayKey || field.key) + '</span></div>' +
    '<div>' + control + '</div>' +
    '<div class="setting-guide"><span>기본 ' + escapeHtml(defaultText) + '</span><strong>추천 ' + escapeHtml(recommendedText) + '</strong></div>' +
    '<div class="setting-description">' + escapeHtml(field.description) + '</div></div>';
}

function updateToggleLabel(event) {
  const toggle = event.target;
  const state = toggle.parentElement.querySelector('.setting-toggle-state');
  state.textContent = toggle.checked ? '사용' : '사용 안 함';
}

function applyRecommendedSettings() {
  SETTINGS_FIELDS.forEach(field => {
    if (field.recommended == null) return;
    const input = document.querySelector('#settings-form [data-key="' + field.key + '"]');
    if (!input) return;
    if (input.type === 'checkbox') {
      input.checked = field.type === 'crossplay' ? field.recommended === ALL_CROSSPLAY_PLATFORMS : field.recommended === 'True';
      updateToggleLabel({ target: input });
    } else {
      input.value = field.recommended;
    }
  });
  showToast('추천값을 폼에 적용했습니다. 저장해야 서버 설정에 반영됩니다.', 'info');
}

function collectChanges() {
  const changes = {};
  document.querySelectorAll('#settings-form [data-key]').forEach(el => {
    if (el.dataset.key === 'CrossplayPlatforms') {
      changes[el.dataset.key] = el.checked ? ALL_CROSSPLAY_PLATFORMS : STEAM_ONLY_PLATFORM;
    } else {
      changes[el.dataset.key] = el.type === 'checkbox' ? (el.checked ? 'True' : 'False') : el.value;
    }
  });
  return changes;
}

async function saveSettings() {
  try {
    const resp = await apiFetch(API + '/settings', {
      method: 'PUT', body: JSON.stringify(collectChanges()),
    });
    if (resp.ok) {
      const data = await resp.json();
      if (data.applied === false) {
        showToast('저장 완료 — 서버 재시작 시 적용됩니다', 'info');
      } else {
        showToast('설정 저장 완료', 'success');
      }
      loadSettings();
    } else {
      showToast((await resp.json()).error || '저장 실패', 'error');
    }
  } catch (e) { showToast(String(e), 'error'); }
}

async function stopSaveRestart() {
  if (!(await confirmAction('서버를 중지하고 설정 저장 후 재시작합니다. 진행할까요?'))) return;
  try {
    await apiFetch(API + '/stop', { method: 'POST' });
    showToast('서버 중지 완료, 설정 저장 중…', 'info');
    const resp = await apiFetch(API + '/settings', {
      method: 'PUT', body: JSON.stringify(collectChanges()),
    });
    if (!resp.ok) {
      showToast('설정 저장 실패: ' + (await resp.json()).error, 'error');
      return;
    }
    await apiFetch(API + '/start', { method: 'POST' });
    showToast('설정 저장 후 서버 재시작 완료', 'success');
  } catch (e) { showToast(String(e), 'error'); }
  setTimeout(refreshStatus, 2000);
}

/* 브라우저 confirm() 대체 — daisyUI modal, ok 버튼 value="ok" */
function confirmAction(message) {
  return new Promise(function (resolve) {
    var modal = document.getElementById('confirm-modal');
    document.getElementById('confirm-message').textContent = message;
    modal.returnValue = '';
    function onClose() {
      modal.removeEventListener('close', onClose);
      resolve(modal.returnValue === 'ok');
    }
    modal.addEventListener('close', onClose);
    modal.showModal();
  });
}

async function loadGuide() {
  try {
    const resp = await apiFetch(API + '/guide');
    const data = await resp.json();
    document.getElementById('guide-address').textContent = data.address;
    const passwordEl = document.getElementById('guide-password');
    if (data.has_password) {
      passwordEl.textContent = data.password;
    } else {
      passwordEl.textContent = '없음 (공개 서버)';
      document.getElementById('guide-password-copy').classList.add('hidden');
    }
    const parts = [];
    if (data.server_name) parts.push('서버 이름: ' + data.server_name);
    if (data.max_players) parts.push('최대 ' + data.max_players + '명');
    document.getElementById('guide-server-info').textContent = parts.join(' · ');
  } catch (e) { /* 401은 modal 처리 */ }
}

async function copyGuide(elementId, label) {
  const text = document.getElementById(elementId).textContent;
  try {
    await navigator.clipboard.writeText(text);
    showToast(label + ' 복사됨: ' + escapeHtml(text), 'success');
  } catch (e) {
    showToast('복사 실패 - 직접 선택해서 복사해주세요', 'error');
  }
}

/* ── 서버 바이너리 업데이트 ── */
const UPDATE_STEP_LABELS = {
  backup: '세이브 백업 중…', stop: '서버 중지 중…',
  download: '새 버전 다운로드 중…', start: '서버 시작 중…',
};
let updatePollTimer = null;
let updateWasRunning = false;

function renderUpdateState(s) {
  const badge = document.getElementById('update-badge');
  const builds = document.getElementById('update-builds');
  if (!badge) return;
  if (s.status === 'running') {
    badge.className = 'badge badge-info';
    badge.textContent = '업데이트 진행 중';
  } else if (s.update_available === true) {
    badge.className = 'badge badge-warning';
    badge.textContent = '업데이트 필요';
  } else if (s.update_available === false) {
    badge.className = 'badge badge-success';
    badge.textContent = '최신 상태';
  } else {
    badge.className = 'badge badge-ghost';
    badge.textContent = s.checked_at ? '버전 판단 불가' : '빌드 확인 전';
  }
  builds.textContent = (s.local_build ? '빌드 ' + s.local_build : '') +
    (s.update_available === true && s.remote_build ? ' → ' + s.remote_build : '');

  const lastEl = document.getElementById('update-last');
  if (lastEl) {
    lastEl.textContent = s.last_update
      ? '마지막 업데이트: ' + s.last_update.finished_at + ' · 빌드 ' + s.last_update.build
      : '';
  }

  const running = s.status === 'running';
  // 완료(done) 상태는 토스트 + 배지로 충분히 안내되므로 패널을 숨긴다.
  // 실패(failed)는 에러 확인용으로 로그가 있으면 계속 띄워둔다.
  const showPanel = running || (s.status === 'failed' && s.log && s.log.length);
  const panel = document.getElementById('update-progress');
  panel.classList.toggle('hidden', !showPanel);
  document.getElementById('update-spinner').classList.toggle('hidden', !running);
  document.getElementById('update-step').textContent =
    running ? (UPDATE_STEP_LABELS[s.step] || '진행 중…')
      : s.status === 'done' ? '업데이트 완료'
      : s.status === 'failed' ? '업데이트 실패: ' + (s.error || '') : '';
  if (showPanel) {
    const pre = document.getElementById('update-log');
    const atBottom = pre.scrollTop + pre.clientHeight >= pre.scrollHeight - 8;
    pre.textContent = (s.log || []).join('\n');
    if (atBottom) pre.scrollTop = pre.scrollHeight;
  }

  if (updateWasRunning && s.status === 'done') {
    showToast('서버 업데이트 완료', 'success');
    refreshStatus();
  }
  if (updateWasRunning && s.status === 'failed') {
    showToast('서버 업데이트 실패: ' + (s.error || ''), 'error');
  }
  updateWasRunning = running;

  if (running && !updatePollTimer) updatePollTimer = setInterval(pollUpdateStatus, 3000);
  if (!running && updatePollTimer) { clearInterval(updatePollTimer); updatePollTimer = null; }
}

async function pollUpdateStatus() {
  try {
    const resp = await apiFetch(API + '/update/status');
    renderUpdateState(await resp.json());
  } catch (e) { /* 401은 modal 처리 */ }
}

async function checkServerUpdate() {
  const btn = document.getElementById('btn-update-check');
  btn.disabled = true;
  showToast('최신 빌드 확인 중… (최대 1~2분)', 'info');
  try {
    const resp = await apiFetch(API + '/update/check', { method: 'POST' });
    const data = await resp.json();
    if (data.update_available === true) showToast('새 버전이 있습니다 — 서버 업데이트를 실행하세요', 'warning');
    else if (data.update_available === false) showToast('이미 최신 버전입니다', 'success');
    else showToast('버전을 판단할 수 없습니다 (스팀 조회 실패)', 'error');
    await pollUpdateStatus();
  } catch (e) { showToast(String(e), 'error'); }
  btn.disabled = false;
}

async function startServerUpdate() {
  if (!(await confirmAction('서버를 중지하고 새 버전을 다운로드합니다. 수 분이 걸리고 접속 중인 플레이어는 끊깁니다. 진행할까요?'))) return;
  try {
    const resp = await apiFetch(API + '/update', { method: 'POST' });
    if (resp.status === 409) { showToast('이미 업데이트가 진행 중입니다', 'warning'); return; }
    showToast('서버 업데이트 시작', 'info');
    await pollUpdateStatus();
  } catch (e) { showToast(String(e), 'error'); }
}

function initLogViewer() {
  createLogViewer(document.getElementById('palworld-log-viewer'), {
    sources: [
      { id: 'game', label: '게임 로그' },
      { id: 'events', label: '이벤트' },
      { id: 'audit', label: '감사' },
      { id: 'update', label: '업데이트' },
      { id: 'stderr', label: '오류(stderr)' },
      { id: 'flask', label: '시스템(Flask)' },
    ],
    fetchLogs: async function (source, lines, hideNoise) {
      const noise = hideNoise ? '&hide_noise=true' : '';
      const resp = await apiFetch(API + '/logs?source=' + source + '&lines=' + lines + noise);
      return resp.json();
    },
    formatLine: function (line, source) {
      return source === 'events' ? formatPalworldEvent(line) : line;
    },
  });
}

async function loadBackups() {
  try {
    const resp = await apiFetch(API + '/backups');
    const data = await resp.json();
    document.getElementById('backup-list').innerHTML = (data.backups || []).map(b =>
      '<tr><td>' + escapeHtml(b.name) + '</td><td>' + escapeHtml(b.size_mb) + '</td><td>' + escapeHtml(b.created) + '</td></tr>'
    ).join('') || '<tr><td colspan="3">백업 없음</td></tr>';
  } catch (e) { /* ignore */ }
}

async function createBackup() {
  try {
    const resp = await apiFetch(API + '/backups', { method: 'POST' });
    if (resp.ok) {
      showToast('백업 완료: ' + (await resp.json()).name, 'success');
      loadBackups();
    } else {
      showToast((await resp.json()).error || '백업 실패', 'error');
    }
  } catch (e) { showToast(String(e), 'error'); }
}

document.addEventListener('DOMContentLoaded', function () {
  refreshStatus();
  loadHistory();
  loadSettings();
  loadGuide();
  loadBackups();
  initLogViewer();
  pollUpdateStatus();
  setInterval(refreshStatus, 5000);
  setInterval(loadHistory, 10000);
});
