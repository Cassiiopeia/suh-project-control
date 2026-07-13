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

async function refreshStatus() {
  try {
    const resp = await apiFetch(API + '/status');
    const data = await resp.json();
    currentState = data.state;
    const badge = document.getElementById('state-badge');
    badge.textContent = data.state.toUpperCase();
    badge.className = 'badge ' + (data.state === 'running' ? 'badge-success' : 'badge-error');

    if (data.rest_available && data.metrics) {
      document.getElementById('stat-players').textContent = data.metrics.currentplayernum;
      document.getElementById('stat-maxplayers').textContent = '/ ' + data.metrics.maxplayernum + ' 명';
      document.getElementById('stat-fps').textContent = data.metrics.serverfps;
      document.getElementById('stat-uptime').textContent = formatUptime(data.metrics.uptime);
    } else {
      ['stat-players', 'stat-fps', 'stat-uptime'].forEach(id =>
        document.getElementById(id).textContent = '-');
    }

    const tbody = document.getElementById('player-list');
    if (data.players && data.players.length) {
      tbody.innerHTML = data.players.map(p =>
        '<tr><td>' + escapeHtml(p.name) + '</td><td>' + escapeHtml(p.level) + '</td><td>' + Math.round(p.ping) + 'ms</td></tr>'
      ).join('');
    } else {
      tbody.innerHTML = '<tr><td colspan="3">접속자 없음</td></tr>';
    }
  } catch (e) { /* 401은 modal 처리 */ }
}

function formatUptime(seconds) {
  const h = Math.floor(seconds / 3600), m = Math.floor((seconds % 3600) / 60);
  return h + 'h ' + m + 'm';
}

async function controlServer(action) {
  if (!confirm('서버를 ' + action + ' 하시겠습니까?')) return;
  try {
    const resp = await apiFetch(API + '/' + action, { method: 'POST' });
    const data = await resp.json();
    if (data.success) showToast(action + ' 완료', 'success');
    else showToast(data.error || action + ' 실패', 'error');
  } catch (e) {
    showToast(String(e), 'error');
  }
  setTimeout(refreshStatus, 2000);
}

async function loadSettings() {
  try {
    const resp = await apiFetch(API + '/settings');
    const data = await resp.json();
    const form = document.getElementById('settings-form');
    form.innerHTML = SETTINGS_FIELDS.map(field => renderSettingRow(field, data.settings)).join('');
    form.querySelectorAll('input[type="checkbox"]').forEach(toggle => {
      toggle.addEventListener('change', updateToggleLabel);
      updateToggleLabel({ target: toggle });
    });
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
    if (resp.status === 409) {
      showToast('서버 가동 중에는 저장할 수 없습니다. 먼저 중지하세요.', 'warning');
      return;
    }
    if (resp.ok) showToast('설정 저장 완료', 'success');
    else showToast((await resp.json()).error || '저장 실패', 'error');
  } catch (e) { showToast(String(e), 'error'); }
}

async function stopSaveRestart() {
  if (!confirm('서버를 중지하고 설정 저장 후 재시작합니다. 진행할까요?')) return;
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

async function refreshLogs() {
  try {
    const resp = await apiFetch(API + '/logs?lines=200');
    const data = await resp.json();
    const view = document.getElementById('log-view');
    view.textContent = (data.logs || []).join('\n') || '(로그 없음)';
    view.scrollTop = view.scrollHeight;
  } catch (e) { /* ignore */ }
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
  loadSettings();
  refreshLogs();
  loadBackups();
  setInterval(refreshStatus, 5000);
  setInterval(refreshLogs, 10000);
});
