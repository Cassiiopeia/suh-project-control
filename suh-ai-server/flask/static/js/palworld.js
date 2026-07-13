/* 팰월드 관리 페이지 로직. base: /admin/palworld → API는 ../palworld/* */
const API = '../palworld';
let currentState = 'unknown';

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
        '<tr><td>' + p.name + '</td><td>' + p.level + '</td><td>' + Math.round(p.ping) + 'ms</td></tr>'
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
    form.innerHTML = data.editable_keys.map(key => {
      const raw = data.settings[key] || '';
      const value = raw.replace(/^"|"$/g, '');
      const isBool = raw === 'True' || raw === 'False';
      if (isBool) {
        return '<label class="label cursor-pointer justify-start gap-4"><span class="label-text w-56">' + key +
          '</span><input type="checkbox" class="toggle toggle-primary" data-key="' + key + '"' +
          (raw === 'True' ? ' checked' : '') + '></label>';
      }
      return '<label class="label justify-start gap-4"><span class="label-text w-56">' + key +
        '</span><input type="text" class="input input-bordered input-sm w-64" data-key="' + key +
        '" value="' + value.replace(/"/g, '&quot;') + '"></label>';
    }).join('');
  } catch (e) { /* ignore */ }
}

function collectChanges() {
  const changes = {};
  document.querySelectorAll('#settings-form [data-key]').forEach(el => {
    changes[el.dataset.key] = el.type === 'checkbox' ? (el.checked ? 'True' : 'False') : el.value;
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
      '<tr><td>' + b.name + '</td><td>' + b.size_mb + '</td><td>' + b.created + '</td></tr>'
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
