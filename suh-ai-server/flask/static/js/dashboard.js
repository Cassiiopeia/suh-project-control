/* 대시보드 로직. base: /admin → API는 ./* */

function setText(id, value) {
  const el = document.getElementById(id);
  if (el) el.textContent = value;
}

/* ── 상단 상태 stats (Flask·팰월드·접속자) ── */
async function refreshTopStats() {
  try {
    const resp = await apiFetch('./health');
    setText('stat-flask', resp.ok ? '온라인' : '오류');
  } catch (e) {
    setText('stat-flask', '오류');
  }
  try {
    const resp = await apiFetch('./palworld/status');
    const data = await resp.json();
    const running = data.state === 'running';
    setText('stat-palworld', running ? '온라인' : '중지됨');
    setText('stat-palworld-desc', data.state.toUpperCase());
    const badge = document.getElementById('pal-badge');
    badge.textContent = data.state.toUpperCase();
    badge.className = 'badge badge-sm ' + (running ? 'badge-success' : 'badge-error');
    if (data.rest_available && data.metrics) {
      setText('stat-players', data.metrics.currentplayernum);
      setText('stat-players-desc', '/ ' + data.metrics.maxplayernum + ' 명');
    }
  } catch (e) { /* 401 modal은 apiFetch가 처리 */ }
}

/* ── 시스템 리소스 카드 ── */
const SYS_POLL_MS = 10000;

function fmtGb(used, total) {
  return (used != null && total != null) ? used.toFixed(1) + ' / ' + total.toFixed(1) + ' GB' : '-';
}

function series(history, key) {
  return history.map(p => (typeof p[key] === 'number' ? p[key] : NaN));
}

function renderSystem(cur, history) {
  setText('sys-cpu', cur.cpu != null ? cur.cpu.toFixed(0) : '-');
  setText('sys-cpu-desc', cur.cpu_cores != null ? cur.cpu_cores + ' 코어' : '-');
  const cpuTemp = document.getElementById('sys-cpu-temp');
  if (cpuTemp) {
    cpuTemp.classList.toggle('hidden', cur.cpu_temp == null);
    if (cur.cpu_temp != null) cpuTemp.textContent = cur.cpu_temp.toFixed(0) + '°C';
  }
  setText('sys-mem', cur.mem != null ? cur.mem.toFixed(0) : '-');
  setText('sys-mem-desc', fmtGb(cur.mem_used_gb, cur.mem_total_gb));
  sparkline('spark-sys-cpu', series(history, 'cpu'), { min: 0, max: 100, klass: 'text-primary' });
  sparkline('spark-sys-mem', series(history, 'mem'), { min: 0, max: 100, klass: 'text-secondary' });

  const hasGpu = cur.gpu_name != null;
  setText('sys-gpu-name', hasGpu ? cur.gpu_name.replace(/^NVIDIA\s+/, '') : 'GPU 미감지');
  setText('sys-gpu', hasGpu && cur.gpu != null ? cur.gpu.toFixed(0) : '-');
  const gpuBadges = document.getElementById('sys-gpu-badges');
  if (gpuBadges) {
    gpuBadges.innerHTML = '';
    if (hasGpu && cur.gpu_temp != null) {
      gpuBadges.innerHTML += '<span class="badge badge-ghost badge-sm">' + cur.gpu_temp.toFixed(0) + '°C</span>';
    }
    if (hasGpu && cur.gpu_power_w != null) {
      gpuBadges.innerHTML += '<span class="badge badge-ghost badge-sm">' + cur.gpu_power_w.toFixed(0) + 'W</span>';
    }
  }
  setText('sys-vram', (hasGpu && cur.vram_used_mb != null && cur.vram_total_mb != null)
    ? fmtGb(cur.vram_used_mb / 1024, cur.vram_total_mb / 1024) : '-');
  const vramPct = history.map(p =>
    (typeof p.vram_used_mb === 'number' && typeof p.vram_total_mb === 'number' && p.vram_total_mb > 0)
      ? p.vram_used_mb / p.vram_total_mb * 100 : NaN);
  sparkline('spark-sys-gpu', series(history, 'gpu'), { min: 0, max: 100, klass: 'text-success' });
  sparkline('spark-sys-vram', vramPct, { min: 0, max: 100, klass: 'text-warning' });

  const diskBar = document.getElementById('sys-disk-bar');
  if (diskBar && cur.disk != null) diskBar.value = cur.disk;
  setText('sys-disk-label', cur.disk != null
    ? fmtGb(cur.disk_used_gb, cur.disk_total_gb) + ' (' + cur.disk.toFixed(0) + '%)' : '-');
  setText('sys-updated', cur.ts ? cur.ts.replace('T', ' ') : '');
}

async function refreshSystem() {
  try {
    const resp = await apiFetch('./system/metrics?limit=120');
    const data = await resp.json();
    renderSystem(data.current || {}, data.history || []);
  } catch (e) { /* 401 modal은 apiFetch가 처리 */ }
}

/* ── VRAM 점유 분해 + 서비스 제어 ── */

function esc(s) {
  const d = document.createElement('div');
  d.textContent = s == null ? '' : String(s);
  return d.innerHTML;
}

function fmtMib(bytes) {
  return Math.round((bytes || 0) / (1024 * 1024));
}

// /api/ps 합계와 nvidia-smi 실측의 차이가 "그 외 점유"다.
// 이 값이 크면 고아 런너나 데스크톱 앱이 VRAM을 물고 있다는 신호.
function renderVramBreakdown(status) {
  const box = document.getElementById('vram-breakdown');
  if (!box) return;

  const gpu = status && status.gpu;
  if (!gpu || !gpu.available) {
    box.innerHTML = '<span class="text-xs opacity-50">GPU 실측 정보를 수집할 수 없습니다.</span>';
    return;
  }

  const models = status.loaded_models || [];
  const modelMb = models.reduce(function (s, m) { return s + fmtMib(m.size); }, 0);
  const otherMb = Math.max(0, gpu.used_mb - modelMb);

  let html = '<div class="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs">'
    + '<span class="font-semibold">VRAM 점유</span>'
    + '<span>모델 <span class="font-mono">' + modelMb + ' MiB</span></span>'
    + '<span class="opacity-70">그 외 <span class="font-mono">' + otherMb + ' MiB</span></span>'
    + '<span class="opacity-50 font-mono">' + gpu.used_mb + ' / ' + gpu.total_mb + ' MiB</span>'
    + '</div>';

  if (models.length) {
    html += '<div class="flex flex-wrap gap-1 mt-2">' + models.map(function (m) {
      return '<span class="badge badge-ghost badge-sm font-mono">'
        + esc(m.model) + ' · ' + fmtMib(m.size) + 'MiB</span>';
    }).join('') + '</div>';
  } else {
    html += '<div class="text-xs opacity-50 mt-2">현재 VRAM에 로드된 모델이 없습니다.</div>';
  }

  if (status.orphan_runners > 0) {
    html += '<div class="alert alert-warning mt-2 py-2 px-3 text-xs">'
      + '<i data-lucide="alert-triangle" class="size-4"></i>'
      + '<span>Ollama가 인식하지 못하는 고아 런너 <b>' + status.orphan_runners
      + '개</b>가 VRAM을 점유 중입니다. Ollama를 재시작하면 정리됩니다.</span></div>';
  }

  box.innerHTML = html;
  if (window.lucide) window.lucide.createIcons();
}

// 중지·재시작은 되돌리기 어려우므로 반드시 확인을 받는다.
const DESTRUCTIVE_WARN = {
  palworld: { stop: '팰월드 서버를 중지하면 접속 중인 플레이어가 모두 튕깁니다.',
              restart: '팰월드 서버를 재시작하면 접속 중인 플레이어가 모두 튕깁니다.' },
  ollama:   { stop: 'Ollama를 중지하면 진행 중인 추론·벤치마크가 중단됩니다.',
              restart: 'Ollama를 재시작하면 진행 중인 추론·벤치마크가 중단됩니다.' },
};

async function controlService(kind, action, btn) {
  const warn = (DESTRUCTIVE_WARN[kind] || {})[action];
  if (warn && !window.confirm(warn + '\n\n계속할까요?')) return;

  const card = btn.closest('[data-service]');
  if (card) card.querySelectorAll('button').forEach(function (b) { b.disabled = true; });

  try {
    const path = kind === 'palworld' ? './palworld/' + action : './ollama/control/' + action;
    const resp = await apiFetch(path, { method: 'POST', body: JSON.stringify({}) });
    if (!resp.ok) {
      const d = await resp.json().catch(function () { return {}; });
      throw new Error(d.error || ('HTTP ' + resp.status));
    }
  } catch (e) {
    alert('요청 실패: ' + e.message);
  } finally {
    // 폴링을 기다리지 않고 즉시 최신 상태로 갱신
    await refreshServiceControl();
    refreshTopStats();
  }
}

function serviceCard(kind, title, icon, running, stateText, extra) {
  const badge = running ? 'badge-success' : 'badge-error';
  return '<div class="border border-base-200 rounded-lg p-3" data-service="' + kind + '">'
    + '<div class="flex items-center gap-2">'
    + '  <i data-lucide="' + icon + '" class="size-4 text-primary"></i>'
    + '  <span class="font-semibold text-sm">' + title + '</span>'
    + '  <span class="badge badge-sm ' + badge + '">' + esc(stateText) + '</span>'
    + '</div>'
    + (extra ? '<div class="text-xs opacity-60 mt-1">' + extra + '</div>' : '')
    + '<div class="flex gap-1 mt-2">'
    + '  <button class="btn btn-xs btn-success" data-act="start"' + (running ? ' disabled' : '') + '>시작</button>'
    + '  <button class="btn btn-xs btn-error" data-act="stop"' + (running ? '' : ' disabled') + '>중지</button>'
    + '  <button class="btn btn-xs btn-warning" data-act="restart">재시작</button>'
    + '</div></div>';
}

async function refreshServiceControl() {
  const box = document.getElementById('service-control');
  if (!box) return;

  let palHtml = '', ollamaHtml = '';

  try {
    const r = await apiFetch('./palworld/status');
    const d = await r.json();
    const running = d.state === 'running';
    let extra = '';
    if (d.rest_available && d.metrics) {
      extra = '접속자 ' + d.metrics.currentplayernum + ' / ' + d.metrics.maxplayernum + ' 명';
    }
    palHtml = serviceCard('palworld', '팰월드 서버', 'gamepad-2', running,
                          (d.state || '-').toUpperCase(), extra);
  } catch (e) { /* 401 modal은 apiFetch가 처리 */ }

  try {
    const r = await apiFetch('./ollama/status');
    const d = await r.json();
    const n = (d.loaded_models || []).length;
    ollamaHtml = serviceCard('ollama', 'Ollama', 'brain-circuit', !!d.running,
                             d.running ? '구동 중' : '정지됨',
                             '로드된 모델 ' + n + '개');
    renderVramBreakdown(d);
  } catch (e) { /* 401 modal은 apiFetch가 처리 */ }

  box.innerHTML = palHtml + ollamaHtml;
  if (window.lucide) window.lucide.createIcons();
}

document.addEventListener('DOMContentLoaded', function () {
  refreshTopStats();
  refreshSystem();
  refreshServiceControl();

  // 카드가 다시 그려져도 동작하도록 위임으로 바인딩
  const box = document.getElementById('service-control');
  if (box) {
    box.addEventListener('click', function (ev) {
      const btn = ev.target.closest('button[data-act]');
      if (!btn) return;
      const card = btn.closest('[data-service]');
      if (!card) return;
      controlService(card.dataset.service, btn.dataset.act, btn);
    });
  }

  // 탭이 백그라운드면 폴링 스킵 — 안 볼 때 부하 0
  setInterval(function () {
    if (document.hidden) return;
    refreshSystem();
    refreshServiceControl();
  }, SYS_POLL_MS);
});
