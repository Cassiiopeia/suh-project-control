/* Ollama 서비스 관리 대시보드 인터랙션 스크립트. base: /admin/ollama → API: ../ollama/* */
(function () {
  const OLLAMA_API = '../ollama';

  let statusPollingTimer = null;
  let logPollingTimer = null;

  function el(id) { return document.getElementById(id); }

  /* ---------- 1. Ollama 데몬 생사 & VRAM 실시간 모니터링 ---------- */
  async function loadStatus() {
    try {
      const resp = await apiFetch(OLLAMA_API + '/status?t=' + Date.now());
      const data = await resp.json();
      if (!resp.ok) throw new Error(data.error || '상태 조회 실패');

      updateStatusUI(data.running, data.loaded_models || [], data.gpu, data.orphan_runners);
    } catch (e) {
      console.warn("Failed to load Ollama daemon status:", e);
      updateStatusUI(false, [], null, 0);
    }
  }

  // /api/ps 합계와 nvidia-smi 실측의 차이를 보여준다.
  // 둘이 크게 벌어지면 고아 런너나 외부 앱이 VRAM을 물고 있다는 뜻이다.
  function updateGpuUI(gpu, loadedModels, orphanRunners) {
    const box = el('gpu-vram-summary');
    if (!box) return;

    if (!gpu || !gpu.available) {
      box.innerHTML = '<span class="text-xs opacity-50">GPU 실측 정보를 수집할 수 없습니다 (nvidia-smi 미가용).</span>';
      return;
    }

    const modelBytes = (loadedModels || []).reduce((sum, m) => sum + (m.size || 0), 0);
    const modelMb = Math.round(modelBytes / (1024 * 1024));
    const ghostMb = Math.max(0, gpu.used_mb - modelMb);
    const barColor = gpu.usage_percent >= 90 ? 'progress-error'
                   : gpu.usage_percent >= 75 ? 'progress-warning' : 'progress-success';

    let html = ''
      + '<div class="flex items-center justify-between text-xs mb-1">'
      + '  <span class="font-semibold">GPU 실측 VRAM</span>'
      + '  <span class="font-mono">' + gpu.used_mb + ' / ' + gpu.total_mb + ' MiB (' + gpu.usage_percent + '%)</span>'
      + '</div>'
      + '<progress class="progress ' + barColor + ' w-full h-2" value="' + gpu.used_mb + '" max="' + gpu.total_mb + '"></progress>'
      + '<div class="flex flex-wrap gap-x-3 gap-y-1 text-xs mt-1.5 opacity-70">'
      + '  <span>모델 점유 <span class="font-mono">' + modelMb + ' MiB</span></span>'
      + '  <span>그 외 점유 <span class="font-mono">' + ghostMb + ' MiB</span></span>'
      + '</div>';

    if (orphanRunners > 0) {
      html += '<div class="alert alert-warning mt-2 py-2 px-3 text-xs">'
            + '<i data-lucide="alert-triangle" class="size-4"></i>'
            + '<span>Ollama가 인식하지 못하는 고아 추론 런너 <b>' + orphanRunners + '개</b>가 VRAM을 점유 중입니다. '
            + '데몬을 재시작하면 정리됩니다.</span>'
            + '</div>';
    }

    box.innerHTML = html;
    if (window.lucide) window.lucide.createIcons();
  }

  function updateStatusUI(running, loadedModels, gpu, orphanRunners) {
    const badge = el('daemon-status-badge');
    const tableBody = el('vram-table-body');

    updateGpuUI(gpu, loadedModels, orphanRunners);

    // 1. 데몬 지시등 상태 전환
    if (running) {
      badge.className = 'badge badge-success gap-1 text-xs py-2 px-2.5';
      badge.innerHTML = '<span class="size-1.5 rounded-full bg-current animate-pulse"></span>구동 중';
    } else {
      badge.className = 'badge badge-error gap-1 text-xs py-2 px-2.5';
      badge.innerHTML = '<span class="size-1.5 rounded-full bg-current animate-ping"></span>정지됨';
    }

    // 2. VRAM 테이블 렌더링
    if (!running) {
      tableBody.innerHTML = '<tr><td colspan="4" class="text-center py-4 text-xs text-error font-semibold">Ollama 데몬이 정지되어 있어 메모리 정보를 수집할 수 없습니다.</td></tr>';
      return;
    }

    if (!loadedModels.length) {
      tableBody.innerHTML = '<tr><td colspan="4" class="text-center py-4 text-xs opacity-50">현재 VRAM에 로드되어 점유 중인 모델이 없습니다.</td></tr>';
      return;
    }

    tableBody.innerHTML = loadedModels.map(m => {
      const sizeText = m.size ? fmtSize(m.size) : '-';
      const expireTime = m.expires_at ? m.expires_at.slice(11, 19) : '-';
      return '<tr>'
        + '  <td class="font-mono text-left font-semibold break-all text-xs">' + escapeHtml(m.model) + '</td>'
        + '  <td class="font-mono text-xs">' + sizeText + '</td>'
        + '  <td class="font-mono text-xs">' + expireTime + ' (KST)</td>'
        + '  <td>'
        + '    <button class="btn btn-ghost btn-xs text-error btn-model-unload" data-model="' + escapeHtml(m.model) + '" title="해당 모델 메모리 반환">'
        + '      <i data-lucide="trash" class="size-3.5"></i>비우기'
        + '    </button>'
        + '  </td>'
        + '</tr>';
    }).join('');

    // 개별 언로드 클릭 이벤트 등록
    tableBody.querySelectorAll('.btn-model-unload').forEach(btn => {
      btn.addEventListener('click', function() {
        controlOllamaDaemon('unload', btn.dataset.model);
      });
    });

    if (window.lucide) lucide.createIcons();
  }

  function fmtSize(bytes) {
    if (!bytes && bytes !== 0) return '-';
    const gb = bytes / 1024 / 1024 / 1024;
    if (gb >= 1) return gb.toFixed(1) + 'GB';
    return (bytes / 1024 / 1024).toFixed(0) + 'MB';
  }

  /* ---------- 2. Ollama 데몬 및 VRAM 조작 신호 전송 ---------- */
  async function controlOllamaDaemon(action, modelName = null) {
    const summaryMsg = {
      start: 'Ollama 시작 신호를 전송 중...',
      stop: 'Ollama 정지 신호를 전송 중...',
      restart: 'Ollama 재기동 신호를 전송 중...',
      unload: '메모리 반환 처리 중...'
    };

    showToast(summaryMsg[action] || '조작 처리 중...', 'info');

    // UI 임시 비활성화 가드
    if (action === 'restart' || action === 'stop' || action === 'start') {
      setButtonsDisabled(true);
    }

    try {
      const resp = await apiFetch(OLLAMA_API + '/control/' + action, {
        method: 'POST',
        body: JSON.stringify({ model: modelName })
      });
      const data = await resp.json();
      if (!resp.ok) throw new Error(data.error || '조작 실패');

      showToast(data.summary || '조작 처리가 성공적으로 완수되었습니다.', 'success');
    } catch (e) {
      showToast('Ollama 데몬 제어 실패: ' + e.message, 'error');
    } finally {
      setButtonsDisabled(false);
      loadStatus();
      loadLogs();
    }
  }

  function setButtonsDisabled(disabled) {
    el('daemon-start').disabled = disabled;
    el('daemon-stop').disabled = disabled;
    el('daemon-restart').disabled = disabled;
    el('vram-unload-all').disabled = disabled;
  }

  /* ---------- 3. Ollama server.log 실시간 스트리밍 ---------- */
  async function loadLogs() {
    const logContainer = el('log-container');
    const pathEl = el('log-file-path');
    try {
      const resp = await apiFetch(OLLAMA_API + '/logs?lines=200&t=' + Date.now());
      const data = await resp.json();
      if (!resp.ok) throw new Error(data.error || '로그 조회 실패');

      pathEl.textContent = data.log_file || '';
      
      if (!data.logs || !data.logs.length) {
        logContainer.innerHTML = '<div class="opacity-50 text-center py-10">출력할 로그 데이터가 없습니다.</div>';
        return;
      }

      // 로그 내용 렌더링
      const atBottom = isScrollNearBottom(logContainer);
      logContainer.innerHTML = data.logs.map(line => {
        let lineClass = "opacity-80";
        if (line.includes('[error]') || line.includes('Error') || line.includes('fail')) {
          lineClass = "text-error font-semibold";
        } else if (line.includes('[warn]')) {
          lineClass = "text-warning";
        } else if (line.includes('[info]')) {
          lineClass = "text-info/80";
        }
        return '<div class="leading-relaxed ' + lineClass + '">' + escapeHtml(line) + '</div>';
      }).join('');

      // 사용자가 직접 로그를 올려보는 중이 아니면 최하단 스크롤 자동 포커스
      if (atBottom) {
        logContainer.scrollTop = logContainer.scrollHeight;
      }
    } catch (e) {
      logContainer.innerHTML = '<div class="text-error text-center py-10">Ollama 로그 수집 실패: ' + escapeHtml(e.message) + '</div>';
    }
  }

  function isScrollNearBottom(element) {
    // 35px 범위 내에 있으면 최하단 부착 상태로 판정
    return (element.scrollHeight - element.scrollTop - element.clientHeight) < 35;
  }

  /* ---------- 4. 주기적 폴링 및 바인딩 ---------- */
  function startPolling() {
    // 1) 5초 주기로 구동 상태 갱신
    statusPollingTimer = setInterval(loadStatus, 5000);

    // 2) 5초 주기로 자동 새로고침 체크 시 실시간 로그 갱신
    logPollingTimer = setInterval(function() {
      if (el('log-auto').checked && !document.hidden) {
        loadLogs();
      }
    }, 5000);
  }

  /* ---------- 초기화 ---------- */
  document.addEventListener('DOMContentLoaded', function () {
    loadStatus();
    loadLogs();
    startPolling();

    el('daemon-start').addEventListener('click', function() { controlOllamaDaemon('start'); });
    el('daemon-stop').addEventListener('click', function() { controlOllamaDaemon('stop'); });
    el('daemon-restart').addEventListener('click', function() { controlOllamaDaemon('restart'); });
    el('vram-unload-all').addEventListener('click', function() { controlOllamaDaemon('unload'); });
    el('log-refresh').addEventListener('click', loadLogs);
  });
})();
