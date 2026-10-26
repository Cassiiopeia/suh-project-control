/* Claude 로그인 6자리 코드 페이지. base: /admin/claude-login → API: ../claude-login/code/*
   흐름: 진입 시 자동 대기 요청 > 2초 폴링 > 코드·수신 시각 표시 > 종료 상태면 폴링 중단 */
(function () {
  const API = '../claude-login/code';
  const AUDIT_API = '../audit/logs?category=CLAUDE_LOGIN&limit=10';
  const POLL_INTERVAL_MILLISECONDS = 2000;
  const STEP_ORDER = ['waiting', 'received', 'opening', 'issued'];
  // failure_reason > 화면 문구
  const FAILURE_LABELS = {
    timeout: '10분 동안 로그인 메일이 오지 않았습니다.',
    code_not_found: '링크 화면에서 코드를 찾지 못했습니다. (만료됐거나 이미 사용된 링크일 수 있음)',
    mail_error: 'Gmail 접속에 실패했습니다. 앱 비밀번호를 확인하세요.',
    browser_error: '서버 브라우저 실행에 실패했습니다.',
  };
  const ACTION_LABELS = {
    CLAUDE_CODE_REQUEST: '코드 요청',
    CLAUDE_CODE_ISSUED: '코드 발급',
    CLAUDE_CODE_VIEW: '코드 열람',
  };
  const TIME_FORMAT = new Intl.DateTimeFormat('ko-KR', {
    timeZone: 'Asia/Seoul', hour: 'numeric', minute: '2-digit', second: '2-digit',
  });
  const DATE_TIME_FORMAT = new Intl.DateTimeFormat('ko-KR', {
    timeZone: 'Asia/Seoul', month: '2-digit', day: '2-digit',
    hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false,
  });

  let pollTimer = null;
  let currentState = null;
  let shownScreenshotJobId = null;

  function el(id) { return document.getElementById(id); }

  function escapeHtml(text) {
    return String(text).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  }

  // "오전 9:34:14 수신 · 2분 전"
  function describeReceivedTime(isoText) {
    const receivedAt = new Date(isoText);
    const elapsedSeconds = Math.max(0, Math.round((Date.now() - receivedAt.getTime()) / 1000));
    const elapsedText = elapsedSeconds < 60 ? elapsedSeconds + '초 전' : Math.floor(elapsedSeconds / 60) + '분 전';
    return TIME_FORMAT.format(receivedAt) + ' 수신 · ' + elapsedText;
  }

  /* ---------- 1. 요청 · 폴링 ---------- */
  async function requestCode(trigger) {
    try {
      const resp = await apiFetch(API + '/request', { method: 'POST', body: JSON.stringify({ trigger }) });
      const data = await resp.json();
      if (resp.status === 400 && data.error === 'not_configured') {
        el('config-warning').hidden = false;
        render({ status: 'idle' });
        return;
      }
      render(data);
      startPolling();
    } catch (e) {
      console.warn('claude login request failed:', e);
    }
  }

  async function loadStatus() {
    try {
      const resp = await apiFetch(API + '/status?t=' + Date.now());
      const data = await resp.json();
      render(data);
      if (data.status !== 'running') stopPolling();
      if (data.status === 'issued' || data.status === 'failed') loadRecentLogs();
    } catch (e) {
      console.warn('claude login status failed:', e);
    }
  }

  function startPolling() {
    stopPolling();
    pollTimer = setInterval(loadStatus, POLL_INTERVAL_MILLISECONDS);
  }

  function stopPolling() {
    if (pollTimer) clearInterval(pollTimer);
    pollTimer = null;
  }

  /* ---------- 2. 화면 ---------- */
  function render(state) {
    currentState = state;
    if (state.account) el('account').textContent = state.account;
    if (state.is_configured === false) el('config-warning').hidden = false;
    renderBadge(state.status);
    renderCode(state);
    renderSteps(state);
    renderFailure(state);
    el('wait-again').hidden = state.status === 'running';
  }

  function renderBadge(status) {
    const badge = el('job-badge');
    const badgeByStatus = {
      running: ['badge-info', '<span class="size-1.5 rounded-full bg-current animate-pulse"></span>메일 기다리는 중'],
      issued: ['badge-success', '코드 발급됨'],
      failed: ['badge-error', '실패'],
      expired: ['badge-ghost', '유효시간 만료'],
      idle: ['badge-ghost', '대기 전'],
    };
    const [badgeClass, html] = badgeByStatus[status] || badgeByStatus.idle;
    badge.className = 'badge gap-1 text-xs py-2 px-2.5 ' + badgeClass;
    badge.innerHTML = html;
  }

  function renderCode(state) {
    const hasCode = Boolean(state.code);
    el('login-code').textContent = hasCode ? state.code : '------';
    el('login-code').classList.toggle('opacity-30', !hasCode);
    el('code-copy').disabled = !hasCode;
    el('mail-received').textContent = state.mail_received_at
      ? describeReceivedTime(state.mail_received_at)
      : (state.status === 'running' ? '메일을 기다리는 중' : '수신한 메일 없음');
    renderExpiresIn(state);
  }

  function renderExpiresIn(state) {
    const label = el('expires-in');
    if (!state.code || !state.expires_at) { label.hidden = true; return; }
    const remainingSeconds = Math.max(0, Math.round((new Date(state.expires_at) - Date.now()) / 1000));
    label.hidden = false;
    label.textContent = Math.floor(remainingSeconds / 60) + '분 ' + String(remainingSeconds % 60).padStart(2, '0') + '초 남음';
  }

  function renderSteps(state) {
    const reachedIndex = STEP_ORDER.indexOf(state.step);
    const stepTimes = state.step_times || {};
    document.querySelectorAll('#steps .step').forEach((item) => {
      const step = item.dataset.step;
      const isReached = reachedIndex >= 0 && STEP_ORDER.indexOf(step) <= reachedIndex;
      const isFailedHere = state.status === 'failed' && step === state.step;
      item.classList.toggle('step-primary', isReached && !isFailedHere);
      item.classList.toggle('step-error', isFailedHere);
      item.querySelector('.step-time').textContent = stepTimes[step] ? TIME_FORMAT.format(new Date(stepTimes[step])) : '';
    });
  }

  function renderFailure(state) {
    const message = el('failure-message');
    message.hidden = state.status !== 'failed';
    message.textContent = FAILURE_LABELS[state.failure_reason] || '';
    const image = el('failure-screenshot');
    if (!state.has_screenshot) { image.hidden = true; return; }
    if (shownScreenshotJobId === state.job_id) return;
    shownScreenshotJobId = state.job_id;
    loadScreenshot(image);
  }

  // img src 로는 API 키 헤더를 못 붙여서 blob 으로 받음
  async function loadScreenshot(image) {
    try {
      const resp = await apiFetch(API + '/screenshot?t=' + Date.now());
      if (!resp.ok) return;
      image.src = URL.createObjectURL(await resp.blob());
      image.hidden = false;
    } catch (e) {
      console.warn('screenshot failed:', e);
    }
  }

  /* ---------- 3. 복사 ---------- */
  async function copyCode() {
    if (!currentState || !currentState.code) return;
    try {
      await navigator.clipboard.writeText(currentState.code);
      el('code-copy-label').textContent = '복사됨';
    } catch (e) {
      // http 등 clipboard API 불가 > 코드 텍스트 선택으로 대체
      const range = document.createRange();
      range.selectNodeContents(el('login-code'));
      window.getSelection().removeAllRanges();
      window.getSelection().addRange(range);
      el('code-copy-label').textContent = 'Ctrl+C 로 복사';
    }
    setTimeout(() => { el('code-copy-label').textContent = '코드 복사'; }, 2000);
  }

  /* ---------- 4. 최근 감사 기록 ---------- */
  async function loadRecentLogs() {
    const body = el('recent-logs');
    try {
      const resp = await apiFetch(AUDIT_API);
      const data = await resp.json();
      const rows = data.rows || [];
      body.innerHTML = rows.length ? rows.map((row) =>
        '<tr>' +
          '<td class="whitespace-nowrap font-mono text-xs">' + escapeHtml(DATE_TIME_FORMAT.format(new Date(row.occurred_at))) + '</td>' +
          '<td>' + escapeHtml(ACTION_LABELS[row.action] || row.action) + '</td>' +
          '<td class="font-mono text-xs">' + escapeHtml(row.client_ip || '-') + '</td>' +
          '<td class="text-xs max-w-56 truncate" title="' + escapeHtml(row.user_agent || '') + '">' + escapeHtml(row.user_agent || '-') + '</td>' +
          '<td>' + (row.success ? '<span class="badge badge-success badge-xs">성공</span>' : '<span class="badge badge-error badge-xs">실패</span>') + '</td>' +
        '</tr>').join('')
        : '<tr><td colspan="5" class="opacity-60">기록 없음</td></tr>';
    } catch (e) {
      body.innerHTML = '<tr><td colspan="5" class="opacity-60">감사로그를 불러오지 못했습니다</td></tr>';
    }
  }

  /* ---------- 5. 시작 ---------- */
  document.addEventListener('DOMContentLoaded', () => {
    el('code-copy').addEventListener('click', copyCode);
    el('wait-again').addEventListener('click', () => requestCode('manual'));
    // 남은 시간·"n분 전" 표시는 1초마다 갱신 (폴링 중단 후에도)
    setInterval(() => { if (currentState) { renderCode(currentState); } }, 1000);
    requestCode('auto');
    loadRecentLogs();
  });
})();
