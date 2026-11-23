/* gbrain 팀원 키 (#221): 펼치기(브레인별 상태·마지막 사용) > 발급 > 다시 보기(관리자 키 재확인, 자동 닫힘) > 폐기 > 기존 토큰 연결
   발급·다시 보기 결과는 토큰 카드 결과 창(gbrain-token-result.js)을 재사용, 원문은 그 창 입력칸에만 둠
   브레인 선택지: gbrain-teams.js 의 'gbrain-teams-loaded' 이벤트로 채움 */
(function () {
  const { getElement, readResponseBody, describeFailure } = window.gbrainPage;
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
  // 결과 창 자동 닫힘 타이머 (다시 보기)
  let autoHideTimer = null;

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

  /* ---------- 1. 펼치기 ---------- */
  function findKeysRow(memberId) { return document.querySelector('[data-member-keys-row="' + memberId + '"]'); }

  function toggleKeys(member) {
    const keysRow = findKeysRow(member.id);
    keysRow.hidden = !keysRow.hidden;
    if (!keysRow.hidden) loadKeys(member);
  }

  async function loadKeys(member) {
    const cell = findKeysRow(member.id).firstElementChild;
    cell.innerHTML = '<div class="text-xs opacity-60 py-2">키 상태를 불러오는 중이에요...</div>';
    try {
      const response = await apiFetch(MEMBER_API + '/' + member.id + '/keys?t=' + Date.now());
      const responseBody = await readResponseBody(response);
      if (!response.ok) throw new Error(describeFailure(responseBody, '키 목록을 불러오지 못했어요'));
      renderKeys(cell, member, responseBody.keys || []);
    } catch (error) {
      cell.innerHTML = '<div class="text-xs text-error py-2">' + escapeHtml(error.message) + '</div>';
    }
  }

  function renderKeys(cell, member, keys) {
    if (!keys.length) {
      cell.innerHTML = '<div class="text-xs opacity-60 py-2">아직 준 키가 없어요.</div>';
      return;
    }
    cell.innerHTML = '<table class="table table-xs"><thead><tr><th>브레인</th><th>키 이름</th><th>권한</th><th>상태</th>' +
      '<th>발급</th><th>마지막 사용</th><th class="text-right">관리</th></tr></thead><tbody>' +
      keys.map(renderKeyRow).join('') + '</tbody></table>';
    cell.querySelectorAll('[data-key-action]').forEach(function (button) {
      button.addEventListener('click', function () {
        const key = keys.find(function (item) { return String(item.id) === button.dataset.keyId; });
        if (button.dataset.keyAction === 'reveal') openReveal(key);
        else revokeKey(member, key, button);
      });
    });
    if (window.lucide) lucide.createIcons();
  }

  function renderKeyRow(key) {
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
    const storedHint = key.has_stored_secret ? '' : '<div class="text-[10px] opacity-50">원문 없음 (기존 토큰 연결)</div>';
    return '<tr class="' + (key.is_revoked ? 'opacity-50' : '') + '">' +
      '<td class="font-mono">' + escapeHtml(key.brain) + '</td>' +
      '<td><div class="font-mono break-all">' + escapeHtml(key.token_name) + '</div>' + storedHint + '</td>' +
      '<td class="whitespace-nowrap">' + escapeHtml(SCOPE_LABELS[key.scopes.join(',')] || key.scopes.join(',')) + '</td>' +
      '<td><span class="badge ' + badge[0] + ' badge-sm whitespace-nowrap">' + escapeHtml(badge[1]) + '</span></td>' +
      '<td class="whitespace-nowrap">' + escapeHtml(formatDateTime(key.issued_at)) + '</td>' +
      '<td class="whitespace-nowrap">' + escapeHtml(key.last_used_at ? formatDateTime(key.last_used_at) : '-') + '</td>' +
      '<td class="text-right"><div class="flex justify-end gap-1">' + buttons.join('') + '</div></td></tr>';
  }

  function refreshAfterChange(member) {
    window.gbrainMembers.reload().then(function () {
      const keysRow = findKeysRow(member.id);
      if (keysRow) { keysRow.hidden = false; loadKeys(member); }
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
      openResultWindow(issued, false);
      refreshAfterChange({ id: Number(modal.dataset.memberId) });
    } catch (error) {
      getElement('member-key-issue-error').textContent = error.message;
      getElement('member-key-issue-error').hidden = false;
    } finally {
      getElement('member-key-issue-submit').disabled = false;
    }
  }

  // 토큰 카드 결과 창 재사용 + 팀원 키 문구 (다시 보기면 자동 닫힘)
  function openResultWindow(responseBody, isReveal) {
    window.gbrainTokenResult.open(responseBody, responseBody.mcp_url, responseBody.mcp_server_name);
    getElement('token-secret-title').textContent = responseBody.token.name + (isReveal ? ' 키 다시 보기' : ' 키를 발급했어요');
    getElement('token-secret-warning').textContent = isReveal
      ? responseBody.auto_hide_seconds + '초 뒤에 창이 저절로 닫히고 값도 지워져요. 그 팀원에게만 1:1 로 보내 주세요.'
      : '관제소에 암호화해 보관했어요. 잃어버리면 팀원 행의 "다시 보기"로 다시 꺼낼 수 있어요.';
    clearTimeout(autoHideTimer);
    if (isReveal) {
      autoHideTimer = setTimeout(function () { getElement('token-secret-modal').close(); }, responseBody.auto_hide_seconds * 1000);
    }
  }

  /* ---------- 3. 다시 보기 ---------- */
  function openReveal(key) {
    getElement('member-reveal-form').reset();
    getElement('member-reveal-modal').dataset.keyId = key.id;
    getElement('member-reveal-error').hidden = true;
    getElement('member-reveal-modal').showModal();
    getElement('member-reveal-admin-key').focus();
  }

  async function submitReveal(event) {
    event.preventDefault();
    const modal = getElement('member-reveal-modal');
    const adminKeyInput = getElement('member-reveal-admin-key');
    const adminKey = adminKeyInput.value;
    adminKeyInput.value = '';  // 보낸 뒤 입력칸에 남기지 않음
    getElement('member-reveal-submit').disabled = true;
    try {
      const revealed = await postJson(KEY_API + '/' + modal.dataset.keyId + '/reveal', { admin_key: adminKey },
        '키를 다시 보지 못했어요');
      modal.close();
      openResultWindow(revealed, true);
    } catch (error) {
      getElement('member-reveal-error').textContent = error.message;
      getElement('member-reveal-error').hidden = false;
    } finally {
      getElement('member-reveal-submit').disabled = false;
    }
  }

  /* ---------- 4. 폐기 ---------- */
  async function revokeKey(member, key, button) {
    if (!window.confirm('"' + key.token_name + '" 키를 폐기할까요?\n\n폐기하면 그 연결이 바로 끊기고 되돌릴 수 없어요.')) return;
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

  /* ---------- 5. 기존 토큰 연결 ---------- */
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
    tokenSelect.innerHTML = '<option value="">불러오는 중이에요...</option>';
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
        : '<option value="">연결할 토큰이 없어요</option>';
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
    getElement('member-reveal-form').addEventListener('submit', submitReveal);
    getElement('member-link-brain-select').addEventListener('change', loadUnrecordedTokens);
    getElement('member-link-form').addEventListener('submit', submitLink);
    getElement('token-secret-modal').addEventListener('close', function () { clearTimeout(autoHideTimer); });
  });
})();
