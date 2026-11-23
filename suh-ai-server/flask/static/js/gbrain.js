/* gbrain HTTP 서버 관리 페이지: 상태 > 제어 > 관리자 화면 로그인 > 로그. base: /admin/gbrain > API: ../gbrain/* */
(function () {
  const { getElement, readResponseBody, describeFailure, SERVICE_STATE_LABELS } = window.gbrainPage;
  const API = '../gbrain';
  const STATUS_REFRESH_MILLISECONDS = 5000;
  const LOG_REFRESH_MILLISECONDS = 5000;

  /* ---------- 1. 상태 ---------- */
  async function loadStatus() {
    try {
      const response = await apiFetch(API + '/status?t=' + Date.now());
      const status = await readResponseBody(response);
      if (!response.ok) throw new Error(describeFailure(status, '상태를 확인하지 못했어요'));
      renderStatus(status);
    } catch (error) {
      console.warn('gbrain status failed:', error);
      renderStatus(null, error.message);
    }
  }

  function setBadge(id, badgeClass, text) {
    const badge = getElement(id);
    badge.className = 'badge ' + badgeClass + ' badge-sm whitespace-nowrap';
    badge.textContent = text;
  }

  // failureMessage: 상태 조회 실패 문구(에러 코드 포함) > 배지 툴팁
  function renderStatus(status, failureMessage) {
    const serviceBadge = getElement('service-status-badge');
    serviceBadge.title = failureMessage || '';
    if (!status) {
      serviceBadge.className = 'badge badge-ghost gap-1 text-xs py-2 px-2.5 whitespace-nowrap';
      serviceBadge.textContent = '확인하지 못했어요';
      return;
    }

    const stateLabel = SERVICE_STATE_LABELS[status.service_state] || status.service_state;
    if (status.service_running) {
      serviceBadge.className = 'badge badge-success gap-1 text-xs py-2 px-2.5 whitespace-nowrap';
      serviceBadge.innerHTML = '<span class="size-1.5 rounded-full bg-current animate-pulse"></span>' + escapeHtml(stateLabel);
    } else {
      serviceBadge.className = 'badge badge-error gap-1 text-xs py-2 px-2.5 whitespace-nowrap';
      serviceBadge.textContent = stateLabel;
    }

    // 서비스는 구동 중인데 헬스가 없으면 기동 직후이거나 DB 연결 대기
    if (status.is_healthy) setBadge('health-badge', 'badge-success', '정상');
    else setBadge('health-badge', status.service_running ? 'badge-warning' : 'badge-ghost', '응답 없음');

    getElement('running-version').textContent = status.version || '-';
    getElement('installed-version').textContent = (status.installed_version || '-') +
      (status.is_restart_pending ? ' (재시작 필요)' : '');
    getElement('service-name').textContent = status.service_name || '-';

    renderConfig(status);
    const hasAdminToken = !!status.has_admin_token;
    getElement('admin-token-warning').hidden = hasAdminToken;
    getElement('admin-login').disabled = !hasAdminToken;
    setBadge('admin-token-badge', hasAdminToken ? 'badge-success' : 'badge-warning', hasAdminToken ? '준비됨' : '없음');
  }

  function renderConfig(status) {
    if (status.config_error) {
      getElement('engine').textContent = '설정 파일을 읽지 못했어요';
      return;
    }
    const database = status.database || {};
    getElement('engine').textContent = status.engine || '-';
    getElement('database').textContent = database.host ? database.host + ':' + database.port + ' / ' + database.name : '-';
    getElement('database-user').textContent = database.user || '-';
    getElement('embedding-model').textContent = status.embedding_model
      ? status.embedding_model + ' (' + status.embedding_dimensions + '차원)' : '-';
    getElement('server-url').textContent = status.server_url || '-';
  }

  /* ---------- 2. 서비스 제어 ---------- */
  // 중지·재시작은 연결된 모든 세션을 끊음 > 확인 후 실행 (팀 브레인 재시작과 같은 기준)
  const CONTROL_CONFIRM_MESSAGES = {
    stop: 'gbrain 서버를 중지할까요?\n\n중지하면 이 서버에 붙은 모든 Claude Code 세션의 gbrain 도구가 끊겨요. 다시 쓰려면 "서비스 시작"을 눌러요.',
    restart: 'gbrain 서버를 재시작할까요?\n\n재시작하는 몇 초 동안 이 서버에 붙은 모든 Claude Code 세션의 gbrain 연결이 잠깐 끊겨요.',
  };

  async function controlService(action) {
    if (CONTROL_CONFIRM_MESSAGES[action] && !window.confirm(CONTROL_CONFIRM_MESSAGES[action])) return;
    const pendingMessages = { start: '서비스를 시작하고 있어요...', stop: '서비스를 중지하고 있어요...', restart: '서비스를 재시작하고 있어요...' };
    showToast(pendingMessages[action] || '처리하고 있어요...', 'info');
    setControlDisabled(true);
    try {
      const response = await apiFetch(API + '/control/' + action, { method: 'POST', body: JSON.stringify({}) });
      const responseBody = await readResponseBody(response);
      if (!response.ok) throw new Error(describeFailure(responseBody, '서버를 제어하지 못했어요'));
      showToast(responseBody.summary || '처리했어요', 'success');
    } catch (error) {
      showToast('gbrain 서버를 제어하지 못했어요: ' + escapeHtml(error.message), 'error');
    } finally {
      setControlDisabled(false);
      // DB 연결·헬스가 뜨기까지 수 초 걸림
      setTimeout(loadStatus, 2000);
      setTimeout(loadStatus, 8000);
    }
  }

  function setControlDisabled(isDisabled) {
    ['service-start', 'service-stop', 'service-restart'].forEach(function (id) { getElement(id).disabled = isDisabled; });
  }

  /* ---------- 3. 관리자 화면 로그인 (1회용 경로 > 같은 출처 /admin/auth/...) ---------- */
  async function openAdminDashboard() {
    getElement('admin-login').disabled = true;
    try {
      const response = await apiFetch(API + '/admin-login', { method: 'POST', body: JSON.stringify({}) });
      const responseBody = await readResponseBody(response);
      if (!response.ok) throw new Error(describeFailure(responseBody, '로그인 링크를 만들지 못했어요'));
      // 경로는 서버가 /admin/auth/<64자 hex> 로 검증 > 출처 루트 기준 이동
      window.location.assign(responseBody.login_path);
    } catch (error) {
      showToast('gbrain 관리자 화면을 열지 못했어요: ' + escapeHtml(error.message), 'error');
      getElement('admin-login').disabled = false;
    }
  }

  /* ---------- 4. 로그 ---------- */
  async function loadLogs() {
    const box = getElement('log-container');
    try {
      const response = await apiFetch(API + '/logs?lines=200&t=' + Date.now());
      const responseBody = await readResponseBody(response);
      if (!response.ok) throw new Error(describeFailure(responseBody, '로그를 불러오지 못했어요'));
      if (!responseBody.logs || !responseBody.logs.length) {
        box.innerHTML = '<div class="opacity-50 text-center py-10">아직 쌓인 로그가 없어요.</div>';
        return;
      }
      const isScrolledToBottom = (box.scrollHeight - box.scrollTop - box.clientHeight) < 35;
      box.innerHTML = responseBody.logs.map(function (line) {
        let lineClass = 'opacity-80';
        if (/error|fatal|failed/i.test(line)) lineClass = 'text-error font-semibold';
        else if (/warn|degraded/i.test(line)) lineClass = 'text-warning';
        else if (/dispatch op=/.test(line)) lineClass = 'text-info/80';
        return '<div class="leading-relaxed ' + lineClass + '">' + escapeHtml(line) + '</div>';
      }).join('');
      if (isScrolledToBottom) box.scrollTop = box.scrollHeight;
    } catch (error) {
      box.innerHTML = '<div class="text-error text-center py-10">gbrain 서버 로그를 불러오지 못했어요: ' + escapeHtml(error.message) + '</div>';
    }
  }

  /* ---------- 초기화 ---------- */
  document.addEventListener('DOMContentLoaded', function () {
    loadStatus();
    loadLogs();
    setInterval(loadStatus, STATUS_REFRESH_MILLISECONDS);
    setInterval(function () {
      if (getElement('log-auto').checked && !document.hidden) loadLogs();
    }, LOG_REFRESH_MILLISECONDS);

    getElement('service-start').addEventListener('click', function () { controlService('start'); });
    getElement('service-stop').addEventListener('click', function () { controlService('stop'); });
    getElement('service-restart').addEventListener('click', function () { controlService('restart'); });
    getElement('admin-login').addEventListener('click', openAdminDashboard);
    getElement('log-refresh').addEventListener('click', loadLogs);
  });
})();
