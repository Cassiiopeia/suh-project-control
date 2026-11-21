/* gbrain HTTP 서버 관리 페이지: 상태 > 제어 > 관리자 화면 로그인 > 로그. base: /admin/gbrain > API: ../gbrain/* */
(function () {
  const API = '../gbrain';
  const STATUS_REFRESH_MILLISECONDS = 5000;
  const LOG_REFRESH_MILLISECONDS = 5000;

  // 서비스 상태 코드 > 표시 문구 (그 외는 원문)
  const SERVICE_STATE_LABELS = {
    running: '구동 중', stopped: '정지됨', start_pending: '시작 중', stop_pending: '중지 중',
    not_installed: '미설치', unknown: '확인 불가',
  };

  function el(id) { return document.getElementById(id); }

  async function readJson(response) {
    try { return await response.json(); } catch (e) { return {}; }
  }

  /* ---------- 1. 상태 ---------- */
  async function loadStatus() {
    try {
      const response = await apiFetch(API + '/status?t=' + Date.now());
      const status = await readJson(response);
      if (!response.ok) throw new Error(status.error || '상태 조회 실패');
      renderStatus(status);
    } catch (error) {
      console.warn('gbrain status failed:', error);
      renderStatus(null);
    }
  }

  function setBadge(id, badgeClass, text) {
    const badge = el(id);
    badge.className = 'badge ' + badgeClass + ' badge-sm';
    badge.textContent = text;
  }

  function renderStatus(status) {
    const serviceBadge = el('service-status-badge');
    if (!status) {
      serviceBadge.className = 'badge badge-ghost gap-1 text-xs py-2 px-2.5';
      serviceBadge.textContent = '조회 실패';
      return;
    }

    const stateLabel = SERVICE_STATE_LABELS[status.service_state] || status.service_state;
    if (status.service_running) {
      serviceBadge.className = 'badge badge-success gap-1 text-xs py-2 px-2.5';
      serviceBadge.innerHTML = '<span class="size-1.5 rounded-full bg-current animate-pulse"></span>' + escapeHtml(stateLabel);
    } else {
      serviceBadge.className = 'badge badge-error gap-1 text-xs py-2 px-2.5';
      serviceBadge.textContent = stateLabel;
    }

    // 서비스는 구동 중인데 헬스가 없으면 기동 직후이거나 DB 연결 대기
    if (status.is_healthy) setBadge('health-badge', 'badge-success', '정상');
    else setBadge('health-badge', status.service_running ? 'badge-warning' : 'badge-ghost', '응답 없음');

    el('running-version').textContent = status.version || '-';
    el('installed-version').textContent = (status.installed_version || '-') +
      (status.is_restart_pending ? ' (재시작 필요)' : '');
    el('service-name').textContent = status.service_name || '-';

    renderConfig(status);
    const hasAdminToken = !!status.has_admin_token;
    el('admin-token-warning').hidden = hasAdminToken;
    el('admin-login').disabled = !hasAdminToken;
    setBadge('admin-token-badge', hasAdminToken ? 'badge-success' : 'badge-warning', hasAdminToken ? '준비됨' : '없음');
  }

  function renderConfig(status) {
    if (status.config_error) {
      el('engine').textContent = '설정 파일을 읽을 수 없음';
      return;
    }
    const database = status.database || {};
    el('engine').textContent = status.engine || '-';
    el('database').textContent = database.host ? database.host + ':' + database.port + ' / ' + database.name : '-';
    el('database-user').textContent = database.user || '-';
    el('embedding-model').textContent = status.embedding_model
      ? status.embedding_model + ' (' + status.embedding_dimensions + '차원)' : '-';
    el('server-url').textContent = status.server_url || '-';
  }

  /* ---------- 2. 서비스 제어 ---------- */
  async function controlService(action) {
    const pendingMessages = { start: '서비스 시작 신호 전송 중...', stop: '서비스 중지 신호 전송 중...', restart: '서비스 재시작 중...' };
    showToast(pendingMessages[action] || '처리 중...', 'info');
    setControlDisabled(true);
    try {
      const response = await apiFetch(API + '/control/' + action, { method: 'POST', body: JSON.stringify({}) });
      const result = await readJson(response);
      if (!response.ok) throw new Error(result.error || '제어 실패');
      showToast(result.summary || '처리했습니다.', 'success');
    } catch (error) {
      showToast('gbrain 서버 제어 실패: ' + escapeHtml(error.message), 'error');
    } finally {
      setControlDisabled(false);
      // DB 연결·헬스가 뜨기까지 수 초 걸림
      setTimeout(loadStatus, 2000);
      setTimeout(loadStatus, 8000);
    }
  }

  function setControlDisabled(isDisabled) {
    ['service-start', 'service-stop', 'service-restart'].forEach(function (id) { el(id).disabled = isDisabled; });
  }

  /* ---------- 3. 관리자 화면 로그인 (1회용 경로 > 같은 출처 /admin/auth/...) ---------- */
  async function openAdminDashboard() {
    el('admin-login').disabled = true;
    try {
      const response = await apiFetch(API + '/admin-login', { method: 'POST', body: JSON.stringify({}) });
      const result = await readJson(response);
      if (!response.ok) throw new Error((result.error || '로그인 링크 발급 실패') + (result.code ? ' [' + result.code + ']' : ''));
      // 경로는 서버가 /admin/auth/<64자 hex> 로 검증 > 출처 루트 기준 이동
      window.location.assign(result.login_path);
    } catch (error) {
      showToast('gbrain 관리자 화면 열기 실패: ' + escapeHtml(error.message), 'error');
      el('admin-login').disabled = false;
    }
  }

  /* ---------- 4. 로그 ---------- */
  async function loadLogs() {
    const box = el('log-container');
    try {
      const response = await apiFetch(API + '/logs?lines=200&t=' + Date.now());
      const result = await readJson(response);
      if (!response.ok) throw new Error(result.error || '로그 조회 실패');
      if (!result.logs || !result.logs.length) {
        box.innerHTML = '<div class="opacity-50 text-center py-10">출력할 로그가 없습니다.</div>';
        return;
      }
      const isScrolledToBottom = (box.scrollHeight - box.scrollTop - box.clientHeight) < 35;
      box.innerHTML = result.logs.map(function (line) {
        let lineClass = 'opacity-80';
        if (/error|fatal|failed/i.test(line)) lineClass = 'text-error font-semibold';
        else if (/warn|degraded/i.test(line)) lineClass = 'text-warning';
        else if (/dispatch op=/.test(line)) lineClass = 'text-info/80';
        return '<div class="leading-relaxed ' + lineClass + '">' + escapeHtml(line) + '</div>';
      }).join('');
      if (isScrolledToBottom) box.scrollTop = box.scrollHeight;
    } catch (error) {
      box.innerHTML = '<div class="text-error text-center py-10">gbrain 서버 로그 조회 실패: ' + escapeHtml(error.message) + '</div>';
    }
  }

  /* ---------- 초기화 ---------- */
  document.addEventListener('DOMContentLoaded', function () {
    loadStatus();
    loadLogs();
    setInterval(loadStatus, STATUS_REFRESH_MILLISECONDS);
    setInterval(function () {
      if (el('log-auto').checked && !document.hidden) loadLogs();
    }, LOG_REFRESH_MILLISECONDS);

    el('service-start').addEventListener('click', function () { controlService('start'); });
    el('service-stop').addEventListener('click', function () { controlService('stop'); });
    el('service-restart').addEventListener('click', function () { controlService('restart'); });
    el('admin-login').addEventListener('click', openAdminDashboard);
    el('log-refresh').addEventListener('click', loadLogs);
  });
})();
