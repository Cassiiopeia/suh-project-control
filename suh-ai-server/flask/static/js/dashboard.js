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

document.addEventListener('DOMContentLoaded', function () {
  refreshTopStats();
  refreshSystem();
  // 탭이 백그라운드면 폴링 스킵 — 안 볼 때 부하 0
  setInterval(function () { if (!document.hidden) refreshSystem(); }, SYS_POLL_MS);
});
