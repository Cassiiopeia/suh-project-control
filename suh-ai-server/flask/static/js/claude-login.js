/* Claude 로그인 코드 받기 탭. base: /admin/claude-login → API: ../claude-login/code/*
   흐름: 진입 시 사용 중 계정 전체 자동 대기 > 2초 폴링 > 계정 카드별 코드·단계 표시 > 진행 중 계정 없으면 폴링 중단
   계정 관리 탭(claude-login-accounts.js)이 계정을 바꾸면 'claude-login:accounts-changed' 이벤트로 다시 조회 */
(function () {
  const API = '../claude-login/code';
  const AUDIT_API = '../audit/logs?category=CLAUDE_LOGIN&limit=10';
  const POLL_INTERVAL_MILLISECONDS = 2000;
  const STEP_ORDER = ['waiting', 'received', 'opening', 'issued'];
  const STEP_LABELS = { waiting: '대기', received: '수신', opening: '열기', issued: '획득' };
  // failure_reason > 화면 문구
  const FAILURE_LABELS = {
    timeout: '10분 동안 로그인 메일이 오지 않았습니다.',
    code_not_found: '링크 화면에서 코드를 찾지 못했습니다. (만료됐거나 이미 사용된 링크일 수 있음)',
    mail_error: 'Gmail 접속에 실패했습니다. 앱 비밀번호를 확인하세요.',
    browser_error: '서버 브라우저 실행에 실패했습니다.',
    decrypt_error: '앱 비밀번호를 복호화하지 못했습니다. 비밀 문구가 바뀌었다면 계정 관리에서 앱 비밀번호를 다시 넣으세요.',
  };
  const ACTION_LABELS = {
    CLAUDE_CODE_REQUEST: '코드 요청',
    CLAUDE_CODE_ISSUED: '코드 발급',
    CLAUDE_CODE_VIEW: '코드 열람',
    CLAUDE_ACCOUNT_CREATE: '계정 추가',
    CLAUDE_ACCOUNT_UPDATE: '계정 수정',
    CLAUDE_ACCOUNT_DELETE: '계정 삭제',
    CLAUDE_ACCOUNT_TEST: '접속 테스트',
  };
  const BADGE_BY_STATUS = {
    running: ['badge-info', '<span class="size-1.5 rounded-full bg-current animate-pulse"></span>기다리는 중'],
    issued: ['badge-success', '코드 발급됨'],
    failed: ['badge-error', '실패'],
    expired: ['badge-ghost', '유효시간 만료'],
    idle: ['badge-ghost', '대기 전'],
  };
  const TIME_FORMAT = new Intl.DateTimeFormat('ko-KR', {
    timeZone: 'Asia/Seoul', hour: 'numeric', minute: '2-digit', second: '2-digit',
  });
  const DATE_TIME_FORMAT = new Intl.DateTimeFormat('ko-KR', {
    timeZone: 'Asia/Seoul', month: '2-digit', day: '2-digit',
    hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false,
  });

  let pollTimer = null;
  let currentStates = [];
  // account_id > 캡처를 이미 불러온 job_id
  const shownScreenshotJobIds = {};
  const screenshotUrls = {};

  function el(id) { return document.getElementById(id); }
  const escapeHtml = window.escapeHtml;

  // "오전 9:34:14 수신 · 2분 전"
  function describeReceivedTime(isoText) {
    const receivedAt = new Date(isoText);
    const elapsedSeconds = Math.max(0, Math.round((Date.now() - receivedAt.getTime()) / 1000));
    const elapsedText = elapsedSeconds < 60 ? elapsedSeconds + '초 전' : Math.floor(elapsedSeconds / 60) + '분 전';
    return TIME_FORMAT.format(receivedAt) + ' 수신 · ' + elapsedText;
  }

  function describeRemaining(isoText) {
    const remainingSeconds = Math.max(0, Math.round((new Date(isoText) - Date.now()) / 1000));
    return Math.floor(remainingSeconds / 60) + '분 ' + String(remainingSeconds % 60).padStart(2, '0') + '초 남음';
  }

  /* ---------- 1. 요청 · 폴링 ---------- */
  async function requestCodes(trigger, accountId) {
    try {
      const body = accountId === undefined ? { trigger } : { trigger, account_id: accountId };
      const response = await apiFetch(API + '/request', { method: 'POST', body: JSON.stringify(body) });
      const responseBody = await response.json();
      if (!response.ok) { showErrorBanner(responseBody.error); return; }
      // request 응답엔 코드가 없음 > 바로 status 조회 (열람 감사 경로)
      await loadStatus();
      startPolling();
    } catch (e) {
      console.warn('claude login request failed:', e);
    }
  }

  async function loadStatus() {
    try {
      const response = await apiFetch(API + '/status?t=' + Date.now());
      const responseBody = await response.json();
      if (!response.ok) { showErrorBanner(responseBody.error); stopPolling(); return; }
      el('store-warning').hidden = true;
      el('secret-warning').hidden = responseBody.is_secret_configured !== false;
      const wasRunning = currentStates.some((state) => state.status === 'running');
      const nextStates = responseBody.accounts || [];
      // 바뀐 게 없으면 다시 그리지 않음 (복사 버튼 문구·코드 선택 유지)
      const hasChanged = JSON.stringify(nextStates) !== JSON.stringify(currentStates);
      currentStates = nextStates;
      if (hasChanged) renderCards();
      const isRunning = currentStates.some((state) => state.status === 'running');
      if (!isRunning) stopPolling();
      if (wasRunning && !isRunning) loadRecentLogs();
    } catch (e) {
      console.warn('claude login status failed:', e);
    }
  }

  function showErrorBanner(errorCode) {
    if (errorCode === 'secret_not_configured') el('secret-warning').hidden = false;
    if (errorCode === 'store_unavailable') el('store-warning').hidden = false;
  }

  function startPolling() {
    stopPolling();
    pollTimer = setInterval(loadStatus, POLL_INTERVAL_MILLISECONDS);
  }

  function stopPolling() {
    if (pollTimer) clearInterval(pollTimer);
    pollTimer = null;
  }

  /* ---------- 2. 계정 카드 ---------- */
  function renderCards() {
    const enabledStates = currentStates.filter((state) => state.is_enabled);
    el('no-accounts').hidden = enabledStates.length > 0;
    el('code-cards').innerHTML = enabledStates.map(renderCard).join('');
    enabledStates.forEach(loadScreenshotIfNeeded);
    if (window.lucide) lucide.createIcons();
  }

  function renderCard(state) {
    const hasCode = Boolean(state.code);
    const [badgeClass, badgeHtml] = BADGE_BY_STATUS[state.status] || BADGE_BY_STATUS.idle;
    const borderClass = hasCode ? 'border-2 border-success' : (state.status === 'failed' ? 'border border-error/60' : 'border border-base-300');
    return '<div class="card bg-base-100 shadow ' + borderClass + '" data-account-id="' + state.account_id + '">' +
      '<div class="card-body gap-3">' +
        '<div class="flex items-start justify-between gap-2"><div class="min-w-0">' +
          '<div class="font-bold">' + escapeHtml(state.display_name) + '</div>' +
          '<div class="font-mono text-xs opacity-70 truncate">' + escapeHtml(state.gmail_address) + '</div></div>' +
          '<span class="badge badge-sm gap-1 ' + badgeClass + '">' + badgeHtml + '</span></div>' +
        '<div class="text-center">' +
          '<div class="font-mono text-5xl font-bold tracking-[0.25em] py-2 select-all' + (hasCode ? '' : ' opacity-30') + '" data-role="code">' +
            (hasCode ? escapeHtml(state.code) : '------') + '</div>' +
          '<div class="text-xs opacity-70" data-role="received">' + describeMailLine(state) + '</div>' +
          (hasCode && state.expires_at ? '<span class="badge badge-outline badge-sm mt-2" data-role="expires">' + describeRemaining(state.expires_at) + '</span>' : '') +
          (state.status === 'failed' ? '<p class="text-sm text-error mt-1">' + escapeHtml(FAILURE_LABELS[state.failure_reason] || '실패했습니다.') + '</p>' : '') +
          '<img class="rounded-box border border-base-300 max-w-full mt-2" data-role="screenshot" alt="코드 화면 캡처"' +
            (state.has_screenshot && screenshotUrls[state.account_id] ? ' src="' + screenshotUrls[state.account_id] + '"' : ' hidden') + '>' +
        '</div>' +
        renderSteps(state) +
        '<div class="card-actions justify-center">' +
          '<button class="btn btn-primary btn-sm" data-action="copy"' + (hasCode ? '' : ' disabled') + '><i data-lucide="copy" class="size-4"></i><span>코드 복사</span></button>' +
          (state.status === 'running' ? '' : '<button class="btn btn-outline btn-sm" data-action="wait"><i data-lucide="rotate-ccw" class="size-4"></i>다시 기다리기</button>') +
        '</div>' +
      '</div></div>';
  }

  function describeMailLine(state) {
    if (state.mail_received_at) return escapeHtml(describeReceivedTime(state.mail_received_at));
    return state.status === 'running' ? '메일을 기다리는 중' : '수신한 메일 없음';
  }

  function renderSteps(state) {
    const reachedIndex = STEP_ORDER.indexOf(state.step);
    const stepTimes = state.step_times || {};
    return '<ul class="steps steps-horizontal w-full text-xs">' + STEP_ORDER.map((step) => {
      const isReached = reachedIndex >= 0 && STEP_ORDER.indexOf(step) <= reachedIndex;
      const isFailedHere = state.status === 'failed' && step === state.step;
      const stepClass = isFailedHere ? ' step-error' : (isReached ? ' step-primary' : '');
      const timeText = stepTimes[step] ? TIME_FORMAT.format(new Date(stepTimes[step])) : '';
      return '<li class="step' + stepClass + '">' + STEP_LABELS[step] +
        '<span class="block text-[10px] opacity-60">' + escapeHtml(timeText) + '</span></li>';
    }).join('') + '</ul>';
  }

  // img src 로는 API 키 헤더를 못 붙여서 blob 으로 받음 (작업당 1회)
  async function loadScreenshotIfNeeded(state) {
    if (!state.has_screenshot || shownScreenshotJobIds[state.account_id] === state.job_id) return;
    shownScreenshotJobIds[state.account_id] = state.job_id;
    try {
      const response = await apiFetch(API + '/screenshot?account_id=' + state.account_id + '&t=' + Date.now());
      if (!response.ok) return;
      screenshotUrls[state.account_id] = URL.createObjectURL(await response.blob());
      renderCards();
    } catch (e) {
      console.warn('screenshot failed:', e);
    }
  }

  /* ---------- 3. 카드 버튼 (복사 · 다시 기다리기) ---------- */
  async function onCardButtonPressed(event) {
    const button = event.target.closest('button[data-action]');
    if (!button) return;
    const card = button.closest('[data-account-id]');
    const accountId = Number(card.dataset.accountId);
    if (button.dataset.action === 'wait') { requestCodes('manual', accountId); return; }
    const state = currentStates.find((item) => item.account_id === accountId);
    if (state && state.code) copyCode(state.code, card, button);
  }

  async function copyCode(code, card, button) {
    const label = button.querySelector('span');
    try {
      await navigator.clipboard.writeText(code);
      label.textContent = '복사됨';
    } catch (e) {
      // http 등 clipboard API 불가 > 코드 텍스트 선택으로 대체
      const range = document.createRange();
      range.selectNodeContents(card.querySelector('[data-role="code"]'));
      window.getSelection().removeAllRanges();
      window.getSelection().addRange(range);
      label.textContent = 'Ctrl+C 로 복사';
    }
    setTimeout(() => { label.textContent = '코드 복사'; }, 2000);
  }

  /* ---------- 4. 최근 감사 기록 ---------- */
  async function loadRecentLogs() {
    const body = el('recent-logs');
    try {
      const response = await apiFetch(AUDIT_API);
      const responseBody = await response.json();
      const rows = responseBody.rows || [];
      body.innerHTML = rows.length ? rows.map((row) =>
        '<tr>' +
          '<td class="whitespace-nowrap font-mono text-xs">' + escapeHtml(DATE_TIME_FORMAT.format(new Date(row.occurred_at))) + '</td>' +
          '<td class="text-xs">' + escapeHtml(describeAuditAccount(row.detail)) + '</td>' +
          '<td>' + escapeHtml(ACTION_LABELS[row.action] || row.action) + '</td>' +
          '<td class="font-mono text-xs">' + escapeHtml(row.client_ip || '-') + '</td>' +
          '<td class="text-xs max-w-56 truncate" title="' + escapeHtml(row.user_agent || '') + '">' + escapeHtml(row.user_agent || '-') + '</td>' +
          '<td>' + (row.success ? '<span class="badge badge-success badge-xs">성공</span>' : '<span class="badge badge-error badge-xs">실패</span>') + '</td>' +
        '</tr>').join('')
        : '<tr><td colspan="6" class="opacity-60">기록 없음</td></tr>';
    } catch (e) {
      body.innerHTML = '<tr><td colspan="6" class="opacity-60">감사로그를 불러오지 못했습니다</td></tr>';
    }
  }

  // 감사 detail > 계정 표시 (이름 우선, 없으면 주소)
  function describeAuditAccount(detail) {
    if (!detail) return '-';
    const accountId = detail.account_id;
    const state = currentStates.find((item) => item.account_id === accountId);
    if (state) return state.display_name;
    return detail.gmail_address || detail.account || (detail.jobs ? detail.jobs.length + '개 계정' : '-');
  }

  /* ---------- 5. 탭 ---------- */
  function showTab(name) {
    document.querySelectorAll('[data-tab]').forEach((tab) => tab.classList.toggle('tab-active', tab.dataset.tab === name));
    el('tab-codes').hidden = name !== 'codes';
    el('tab-accounts').hidden = name !== 'accounts';
  }

  /* ---------- 6. 시작 ---------- */
  document.addEventListener('DOMContentLoaded', () => {
    document.querySelectorAll('[data-tab]').forEach((tab) => tab.addEventListener('click', () => showTab(tab.dataset.tab)));
    el('code-cards').addEventListener('click', onCardButtonPressed);
    el('wait-all').addEventListener('click', () => requestCodes('manual'));
    // 계정 추가·사용 전환 > 새 계정도 바로 대기 (진행 중 계정은 서버가 유지)
    document.addEventListener('claude-login:accounts-changed', () => { requestCodes('auto'); loadRecentLogs(); });
    // 남은 시간·"n분 전" 1초마다 갱신, 유효시간 지나면 다시 조회해 코드 숨김
    setInterval(() => {
      const isAnyExpired = currentStates.some((state) => state.code && state.expires_at && new Date(state.expires_at) <= Date.now());
      if (isAnyExpired) { loadStatus(); return; }
      document.querySelectorAll('#code-cards [data-account-id]').forEach((card) => {
        const state = currentStates.find((item) => item.account_id === Number(card.dataset.accountId));
        if (!state) return;
        card.querySelector('[data-role="received"]').innerHTML = describeMailLine(state);
        const expires = card.querySelector('[data-role="expires"]');
        if (expires && state.expires_at) expires.textContent = describeRemaining(state.expires_at);
      });
    }, 1000);
    requestCodes('auto');
    loadRecentLogs();
  });
})();
