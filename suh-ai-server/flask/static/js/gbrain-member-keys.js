/* gbrain 팀원 키 (#221): 키 목록 펼치기(브레인별 상태·마지막 사용) > 발급 > 폐기(확인 창) > 기존 토큰 연결
   발급 결과·다시 보기는 gbrain-member-key-reveal.js (이 파일보다 먼저 로드)
   브레인 선택지: gbrain-teams.js 의 'gbrain-teams-loaded' 이벤트로 채움 */
(function () {
  const { getElement, readResponseBody, describeFailure, confirmDanger } = window.gbrainPage;
  const MEMBER_API = '../gbrain/members';
  const KEY_API = '../gbrain/member-keys';
  const PAGE_SETTINGS = JSON.parse(document.getElementById('gbrain-token-page-settings').textContent);
  const SCOPE_LABELS = { 'read,write': '읽기 + 쓰기', read: '읽기 전용' };
  // gbrain 상태 > 배지 (missing: gbrain 목록에 없음, unknown: gbrain 확인 실패)
  const LIVE_STATUS_BADGES = {
    active: ['badge-success', '사용 중'], revoked: ['badge-ghost', '폐기됨'],
    missing: ['badge-warning', 'gbrain 에 없음'], unknown: ['badge-ghost', '확인 불가'],
  };
  const DATE_TIME_FORMAT = new Intl.DateTimeFormat('ko-KR', {
    timeZone: 'Asia/Seoul', year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false,
  });

  let brainOptionsHtml = '<option value="' + PAGE_SETTINGS.personal_brain_id + '">개인 브레인 (' +
    PAGE_SETTINGS.personal_mcp_server_name + ')</option>';

  function formatDateTime(value) {
    if (!value) return '-';
    const date = new Date(value);
    return isNaN(date.getTime()) ? '-' : DATE_TIME_FORMAT.format(date);
  }

  async function postJson(url, body, fallbackMessage) {
    const response = await apiFetch(url, { method: 'POST', body: JSON.stringify(body || {}) });
    const responseBody = await readResponseBody(response);
    if (!response.ok) throw new Error(describeFailure(responseBody, fallbackMessage));
    return responseBody;
  }

  /* ---------- 1. 키 목록 펼치기 ---------- */
  function findKeysPanel(memberId) { return document.querySelector('[data-member-keys-panel="' + memberId + '"]'); }

  function setExpanded(memberId, isExpanded) {
    findKeysPanel(memberId).hidden = !isExpanded;
    const toggleButton = document.querySelector('[data-member-action="expand"][data-member-id="' + memberId + '"]');
    toggleButton.setAttribute('aria-expanded', String(isExpanded));
    toggleButton.querySelector('svg, i').classList.toggle('rotate-180', isExpanded);
  }

  function toggleKeys(member) {
    const isExpanded = findKeysPanel(member.id).hidden;
    setExpanded(member.id, isExpanded);
    if (isExpanded) loadKeys(member);
  }

  async function loadKeys(member) {
    const panel = findKeysPanel(member.id);
    panel.innerHTML = '<div class="text-xs opacity-60 py-3">키 상태를 불러오는 중이에요...</div>';
    try {
      const response = await apiFetch(MEMBER_API + '/' + member.id + '/keys?t=' + Date.now());
      const responseBody = await readResponseBody(response);
      if (!response.ok) throw new Error(describeFailure(responseBody, '키 목록을 불러오지 못했어요'));
      renderKeys(panel, member, responseBody.keys || []);
    } catch (error) {
      panel.innerHTML = '<div class="text-xs text-error py-3">' + escapeHtml(error.message) + '</div>';
    }
  }

  function renderKeys(panel, member, keys) {
    if (!keys.length) return renderEmptyKeys(panel, member);
    panel.innerHTML = '<ul class="divide-y divide-base-300">' + keys.map(renderKeyItem).join('') + '</ul>';
    panel.querySelectorAll('[data-key-action]').forEach(function (button) {
      button.addEventListener('click', function () {
        const key = keys.find(function (item) { return String(item.id) === button.dataset.keyId; });
        if (button.dataset.keyAction === 'reveal') window.gbrainMemberKeyReveal.open(key);
        else revokeKey(member, key, button);
      });
    });
    if (window.lucide) lucide.createIcons();
  }

  // 빈 화면: 활성 팀원은 바로 할 수 있는 두 가지(새 키 발급·기존 토큰 연결)를 함께 보여 줌
  function renderEmptyKeys(panel, member) {
    if (!member.is_active) {
      panel.innerHTML = '<div class="text-xs opacity-60 py-3">종료한 팀원이라 받은 키가 없어요.</div>';
      return;
    }
    panel.innerHTML = '<div class="flex flex-col gap-2 py-3 sm:flex-row sm:items-center sm:justify-between">' +
      '<div class="text-xs opacity-70">아직 받은 키가 없어요. 새로 발급하거나, 이미 쓰고 있는 토큰을 연결해 주세요.</div>' +
      '<div class="flex flex-wrap gap-1">' +
      '<button class="btn btn-primary btn-outline btn-xs whitespace-nowrap" data-empty-action="issue"><i data-lucide="key-round" class="size-3"></i>키 발급</button>' +
      '<button class="btn btn-ghost btn-xs whitespace-nowrap" data-empty-action="link"><i data-lucide="link" class="size-3"></i>기존 토큰 연결</button>' +
      '</div></div>';
    panel.querySelectorAll('[data-empty-action]').forEach(function (button) {
      button.addEventListener('click', function () { window.gbrainMembers.runAction(button.dataset.emptyAction, member.id, button); });
    });
    if (window.lucide) lucide.createIcons();
  }

  // 키 1개: 이름·상태 > 브레인·권한·발급·마지막 사용 > 다시 보기·폐기 (좁은 화면은 세로로 쌓임)
  function renderKeyItem(key) {
    const liveStatus = key.is_revoked ? 'revoked' : key.live_status;
    const badge = LIVE_STATUS_BADGES[liveStatus] || ['badge-ghost', liveStatus || '-'];
    const buttons = [];
    if (!key.is_revoked && key.has_stored_secret) {
      buttons.push('<button class="btn btn-ghost btn-xs whitespace-nowrap" data-key-action="reveal" data-key-id="' + key.id +
        '"><i data-lucide="eye" class="size-3"></i>다시 보기</button>');
    }
    if (!key.is_revoked) {
      buttons.push('<button class="btn btn-error btn-outline btn-xs whitespace-nowrap" data-key-action="revoke" data-key-id="' +
        key.id + '"><i data-lucide="ban" class="size-3"></i>폐기</button>');
    }
    const details = [
      escapeHtml(key.brain), escapeHtml(SCOPE_LABELS[key.scopes.join(',')] || key.scopes.join(',')),
      '발급 ' + escapeHtml(formatDateTime(key.issued_at)),
      '마지막 사용 ' + escapeHtml(key.last_used_at ? formatDateTime(key.last_used_at) : '아직 없음'),
    ];
    const storedHint = key.has_stored_secret ? '' : '<div class="text-xs opacity-50">기존 토큰을 연결해서 원문이 없어요</div>';
    return '<li class="flex flex-col gap-2 py-3 md:flex-row md:items-center md:gap-3' + (key.is_revoked ? ' opacity-50' : '') + '">' +
      '<div class="flex-1 min-w-0">' +
      '<div class="flex flex-wrap items-center gap-2"><span class="font-mono text-sm break-all">' + escapeHtml(key.token_name) + '</span>' +
      '<span class="badge ' + badge[0] + ' badge-sm whitespace-nowrap">' + escapeHtml(badge[1]) + '</span></div>' +
      '<div class="text-xs opacity-60 mt-1">' + details.join(' · ') + '</div>' + storedHint +
      '</div>' +
      (buttons.length ? '<div class="flex flex-wrap gap-1 shrink-0">' + buttons.join('') + '</div>' : '') +
      '</li>';
  }

  function refreshAfterChange(member) {
    // 다시 그린 목록의 최신 팀원 값으로 펼침 (활성 여부에 따라 빈 화면이 달라짐)
    window.gbrainMembers.reload().then(function () {
      const freshMember = window.gbrainMembers.find(member.id);
      if (freshMember && findKeysPanel(freshMember.id)) { setExpanded(freshMember.id, true); loadKeys(freshMember); }
    });
  }

  /* ---------- 2. 발급 ---------- */
  function openIssue(member, isKeySecretConfigured) {
    if (!isKeySecretConfigured) {
      showToast('서버에 암호화 비밀 문구가 없어서 발급할 수 없어요 [member_key_secret_missing]', 'error');
      return;
    }
    getElement('member-key-issue-form').reset();
    getElement('member-key-issue-target').textContent = member.display_name + ' (' + member.handle + ')';
    getElement('member-key-brain-select').innerHTML = brainOptionsHtml;
    getElement('member-key-issue-modal').dataset.memberId = member.id;
    getElement('member-key-issue-modal').dataset.handle = member.handle;
    fillDefaultKeyName();
    getElement('member-key-issue-error').hidden = true;
    getElement('member-key-issue-modal').showModal();
  }

  function fillDefaultKeyName() {
    getElement('member-key-name').value = getElement('member-key-issue-modal').dataset.handle + '-' +
      getElement('member-key-brain-select').value;
  }

  async function submitIssue(event) {
    event.preventDefault();
    const modal = getElement('member-key-issue-modal');
    const scopeInput = document.querySelector('input[name="member-key-scope-preset"]:checked');
    getElement('member-key-issue-submit').disabled = true;
    try {
      const issued = await postJson(MEMBER_API + '/' + modal.dataset.memberId + '/keys', {
        brain: getElement('member-key-brain-select').value, name: getElement('member-key-name').value.trim(),
        scope_preset: scopeInput ? scopeInput.value : PAGE_SETTINGS.read_only_scope_preset,
      }, '키를 발급하지 못했어요');
      modal.close();
      window.gbrainMemberKeyReveal.showIssued(issued);
      refreshAfterChange({ id: Number(modal.dataset.memberId) });
    } catch (error) {
      getElement('member-key-issue-error').textContent = error.message;
      getElement('member-key-issue-error').hidden = false;
    } finally {
      getElement('member-key-issue-submit').disabled = false;
    }
  }

  /* ---------- 3. 폐기 (확인 창) ---------- */
  async function revokeKey(member, key, button) {
    const isConfirmed = await confirmDanger({
      title: key.token_name + ' 키를 폐기할까요?',
      message: member.display_name + ' 팀원의 ' + key.brain + ' 브레인 키예요.',
      consequences: ['이 키로 붙은 연결이 바로 끊겨요.', '폐기는 되돌릴 수 없어요. 다시 필요하면 새 키를 발급해 주세요.'],
      confirmLabel: '폐기',
    });
    if (!isConfirmed) return;
    button.disabled = true;
    try {
      await postJson(KEY_API + '/' + key.id + '/revoke', {}, '키를 폐기하지 못했어요');
      showToast(key.token_name + ' 키를 폐기했어요', 'success');
    } catch (error) {
      showToast(escapeHtml(error.message), 'error');
    } finally {
      refreshAfterChange(member);
    }
  }

  /* ---------- 4. 기존 토큰 연결 ---------- */
  function openLink(member) {
    getElement('member-link-target').textContent = member.display_name;
    getElement('member-link-modal').dataset.memberId = member.id;
    getElement('member-link-brain-select').innerHTML = brainOptionsHtml;
    getElement('member-link-error').hidden = true;
    getElement('member-link-modal').showModal();
    loadUnrecordedTokens();
  }

  async function loadUnrecordedTokens() {
    const tokenSelect = getElement('member-link-token-select');
    const submitButton = getElement('member-link-submit');
    tokenSelect.innerHTML = '<option value="">불러오는 중이에요...</option>';
    submitButton.disabled = true;  // 고를 토큰이 있을 때만 연결 가능
    try {
      const response = await apiFetch(MEMBER_API + '/unrecorded-tokens?brain=' +
        encodeURIComponent(getElement('member-link-brain-select').value) + '&t=' + Date.now());
      const responseBody = await readResponseBody(response);
      if (!response.ok) throw new Error(describeFailure(responseBody, '토큰 목록을 불러오지 못했어요'));
      const tokens = responseBody.tokens || [];
      tokenSelect.innerHTML = tokens.length
        ? tokens.map(function (token) {
          return '<option value="' + escapeHtml(token.id) + '">' + escapeHtml(token.name) + ' · ' +
            escapeHtml(formatDateTime(token.created_at)) + '</option>';
        }).join('')
        : '<option value="">이 브레인에는 연결할 토큰이 없어요</option>';
      submitButton.disabled = !tokens.length;
    } catch (error) {
      tokenSelect.innerHTML = '<option value="">' + escapeHtml(error.message) + '</option>';
    }
  }

  async function submitLink(event) {
    event.preventDefault();
    const modal = getElement('member-link-modal');
    const tokenId = getElement('member-link-token-select').value;
    if (!tokenId) return;
    getElement('member-link-submit').disabled = true;
    try {
      await postJson(MEMBER_API + '/' + modal.dataset.memberId + '/keys/link',
        { brain: getElement('member-link-brain-select').value, token_id: tokenId }, '토큰을 연결하지 못했어요');
      modal.close();
      showToast('기존 토큰을 연결했어요', 'success');
      refreshAfterChange({ id: Number(modal.dataset.memberId) });
    } catch (error) {
      getElement('member-link-error').textContent = error.message;
      getElement('member-link-error').hidden = false;
    } finally {
      getElement('member-link-submit').disabled = false;
    }
  }

  window.gbrainMemberKeys = { toggle: toggleKeys, openIssue: openIssue, openLink: openLink };

  document.addEventListener('DOMContentLoaded', function () {
    document.addEventListener('gbrain-teams-loaded', function (event) {
      brainOptionsHtml = '<option value="' + PAGE_SETTINGS.personal_brain_id + '">개인 브레인 (' +
        PAGE_SETTINGS.personal_mcp_server_name + ')</option>' + (event.detail.brains || []).map(function (brain) {
        return '<option value="' + escapeHtml(brain.project) + '">' + escapeHtml(brain.project) + ' 팀 (' +
          escapeHtml(brain.mcp_server_name) + ')</option>';
      }).join('');
    });
    getElement('member-key-brain-select').addEventListener('change', fillDefaultKeyName);
    getElement('member-key-issue-form').addEventListener('submit', submitIssue);
    getElement('member-link-brain-select').addEventListener('change', loadUnrecordedTokens);
    getElement('member-link-form').addEventListener('submit', submitLink);
  });
})();
