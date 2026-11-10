/* Claude 로그인 계정 관리 탭. API: ../claude-login/accounts
   흐름: 목록 조회 > 추가·수정(접속 확인 후 저장) / 사용 전환 / 접속 테스트 / 삭제 > 'claude-login:accounts-changed' 알림 */
(function () {
  const API = '../claude-login/accounts';
  // 서버 error 코드 > 화면 문구
  const ERROR_LABELS = {
    invalid_display_name: '표시 이름을 1~100자로 입력하세요.',
    invalid_gmail_address: 'Gmail 주소 형식이 아닙니다.',
    invalid_app_password: '앱 비밀번호는 영문 16자리입니다.',
    invalid_is_enabled: '사용 여부 값이 잘못됐습니다.',
    imap_login_failed: 'Gmail 접속에 실패했습니다. 주소·앱 비밀번호와 2단계 인증을 확인하세요.',
    duplicate_account: '이미 등록된 Gmail 주소입니다.',
    secret_not_configured: '서버에 암호화 비밀 문구(CLAUDE_LOGIN_ACCOUNT_SECRET)가 없습니다.',
    store_unavailable: '계정 DB에 접속하지 못했습니다.',
    account_not_found: '계정을 찾지 못했습니다. 목록을 새로 고칩니다.',
  };
  const DATE_TIME_FORMAT = new Intl.DateTimeFormat('ko-KR', {
    timeZone: 'Asia/Seoul', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false,
  });

  let accounts = [];
  // 수정 중인 계정 id (추가면 null)
  let editingAccountId = null;

  function el(id) { return document.getElementById(id); }
  const escapeHtml = window.escapeHtml;

  function describeError(errorCode) {
    return ERROR_LABELS[errorCode] || '요청에 실패했습니다.';
  }

  function notifyAccountsChanged() {
    document.dispatchEvent(new CustomEvent('claude-login:accounts-changed'));
  }

  /* ---------- 1. 목록 ---------- */
  async function loadAccounts() {
    try {
      const response = await apiFetch(API + '?t=' + Date.now());
      const responseBody = await response.json();
      if (!response.ok) {
        if (responseBody.error === 'store_unavailable') el('store-warning').hidden = false;
        el('account-rows').innerHTML = '<tr><td colspan="6" class="opacity-60">' + escapeHtml(describeError(responseBody.error)) + '</td></tr>';
        return;
      }
      el('secret-warning').hidden = responseBody.is_secret_configured !== false;
      accounts = responseBody.accounts || [];
      renderAccounts();
    } catch (e) {
      console.warn('claude login accounts failed:', e);
    }
  }

  function renderAccounts() {
    el('account-count').textContent = accounts.length;
    el('account-rows').innerHTML = accounts.length ? accounts.map(renderAccountRow).join('')
      : '<tr><td colspan="6" class="opacity-60">등록된 계정이 없습니다. 계정 추가를 누르세요.</td></tr>';
    if (window.lucide) lucide.createIcons();
  }

  function renderAccountRow(account) {
    const statusBadge = account.is_last_test_failed
      ? '<span class="badge badge-warning badge-sm gap-1"><i data-lucide="alert-triangle" class="size-3"></i>접속 실패</span>'
      : '<span class="badge badge-ghost badge-sm gap-1"><i data-lucide="lock" class="size-3"></i>암호화 저장됨</span>';
    const lastSuccess = account.last_success_at ? DATE_TIME_FORMAT.format(new Date(account.last_success_at)) : '<span class="opacity-60">없음</span>';
    return '<tr data-account-id="' + account.id + '">' +
      '<td class="font-bold">' + escapeHtml(account.display_name) + '</td>' +
      '<td class="font-mono text-xs">' + escapeHtml(account.gmail_address) + '</td>' +
      '<td>' + statusBadge + '</td>' +
      '<td><input type="checkbox" class="toggle toggle-success toggle-sm" data-action="toggle"' + (account.is_enabled ? ' checked' : '') + ' aria-label="사용"></td>' +
      '<td class="text-xs">' + lastSuccess + '</td>' +
      '<td class="text-right whitespace-nowrap">' +
        '<button class="btn btn-ghost btn-xs" data-action="test"><i data-lucide="plug" class="size-3"></i>접속 테스트</button>' +
        '<button class="btn btn-ghost btn-xs" data-action="edit"><i data-lucide="pencil" class="size-3"></i>수정</button>' +
        '<button class="btn btn-ghost btn-xs text-error" data-action="delete" aria-label="삭제"><i data-lucide="trash-2" class="size-3"></i></button>' +
      '</td></tr>';
  }

  /* ---------- 2. 행 버튼 (사용 전환 · 접속 테스트 · 수정 · 삭제) ---------- */
  async function onAccountRowAction(event) {
    const control = event.target.closest('[data-action]');
    if (!control) return;
    const accountId = Number(control.closest('[data-account-id]').dataset.accountId);
    const account = accounts.find((item) => item.id === accountId);
    if (!account) return;
    const action = control.dataset.action;
    if (action === 'toggle') await toggleAccount(account, control.checked);
    if (action === 'test') await testAccount(account, control);
    if (action === 'edit') openAccountModal(account);
    if (action === 'delete') await deleteAccount(account);
  }

  async function toggleAccount(account, isEnabled) {
    const response = await apiFetch(API + '/' + account.id, { method: 'PUT', body: JSON.stringify({ is_enabled: isEnabled }) });
    if (!response.ok) { showToast(describeError((await response.json()).error), 'error'); }
    await loadAccounts();
    notifyAccountsChanged();
  }

  async function testAccount(account, button) {
    button.disabled = true;
    try {
      const response = await apiFetch(API + '/' + account.id + '/test', { method: 'POST' });
      const responseBody = await response.json();
      if (!response.ok) { showToast(describeError(responseBody.error), 'error'); return; }
      // showToast 는 innerHTML 사용 > 사용자 입력 이름은 escape
      const name = escapeHtml(account.display_name);
      showToast(name + (responseBody.is_success ? ' Gmail 접속 성공' : ' Gmail 접속 실패'), responseBody.is_success ? 'success' : 'error');
      await loadAccounts();
    } finally {
      button.disabled = false;
    }
  }

  async function deleteAccount(account) {
    if (!confirm(account.display_name + ' (' + account.gmail_address + ') 계정을 삭제할까요?')) return;
    const response = await apiFetch(API + '/' + account.id, { method: 'DELETE' });
    if (!response.ok) showToast(describeError((await response.json()).error), 'error');
    await loadAccounts();
    notifyAccountsChanged();
  }

  /* ---------- 3. 추가 · 수정 창 ---------- */
  function openAccountModal(account) {
    editingAccountId = account ? account.id : null;
    el('account-modal-title').querySelector('span').textContent = account ? '계정 수정' : '계정 추가';
    el('account-display-name').value = account ? account.display_name : '';
    el('account-gmail-address').value = account ? account.gmail_address : '';
    // 주소는 메일함 식별 기준이라 수정 불가 (바꾸려면 삭제 후 추가)
    el('account-gmail-address').disabled = Boolean(account);
    el('account-app-password').value = '';
    el('account-app-password').required = !account;
    el('account-app-password').placeholder = account ? '바꿀 때만 입력 (16자리)' : '앱 비밀번호 16자리';
    el('account-form-error').hidden = true;
    el('account-modal').showModal();
  }

  function buildAccountRequestBody() {
    const appPassword = el('account-app-password').value;
    const body = { display_name: el('account-display-name').value };
    if (editingAccountId === null) {
      body.gmail_address = el('account-gmail-address').value;
      body.app_password = appPassword;
    } else if (appPassword) {
      body.app_password = appPassword;
    }
    return body;
  }

  async function onAccountFormSubmitted(event) {
    event.preventDefault();
    setSubmitting(true);
    try {
      const isCreating = editingAccountId === null;
      const response = await apiFetch(isCreating ? API : API + '/' + editingAccountId, {
        method: isCreating ? 'POST' : 'PUT', body: JSON.stringify(buildAccountRequestBody()),
      });
      const responseBody = await response.json();
      if (!response.ok) {
        el('account-form-error').textContent = describeError(responseBody.error);
        el('account-form-error').hidden = false;
        return;
      }
      el('account-modal').close();
      showToast((isCreating ? '계정 추가됨: ' : '계정 수정됨: ') + escapeHtml(responseBody.display_name), 'success');
      await loadAccounts();
      notifyAccountsChanged();
    } finally {
      // 앱 비밀번호 입력값은 성공·실패 공통으로 지움
      el('account-app-password').value = '';
      setSubmitting(false);
    }
  }

  function setSubmitting(isSubmitting) {
    el('account-submit').disabled = isSubmitting;
    el('account-submit-spinner').hidden = !isSubmitting;
  }

  /* ---------- 4. 시작 ---------- */
  document.addEventListener('DOMContentLoaded', () => {
    el('account-add').addEventListener('click', () => openAccountModal(null));
    el('account-cancel').addEventListener('click', () => el('account-modal').close());
    el('account-form').addEventListener('submit', onAccountFormSubmitted);
    el('account-rows').addEventListener('click', onAccountRowAction);
    loadAccounts();
  });
})();
