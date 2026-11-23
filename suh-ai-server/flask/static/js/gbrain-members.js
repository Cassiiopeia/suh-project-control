/* gbrain 팀원 카드 (#221): 팀원 목록 > 추가·수정 > 종료(키 일괄 폐기), 펼치기는 gbrain-member-keys.js
   API: ../gbrain/members (GET 목록, POST 추가), ../gbrain/members/{id} (PUT 수정), ../gbrain/members/{id}/end (POST)
   목록 응답에 원문 없음, 암호화 비밀 문구가 없으면 경고를 띄움 */
(function () {
  const { getElement, readResponseBody, describeFailure } = window.gbrainPage;
  const API = '../gbrain/members';

  // 지금 목록 (id > 팀원), 키 스크립트가 받을 팀원 이름을 여기서 찾음
  let memberById = {};
  let isKeySecretConfigured = true;

  function describeMemberStatus(member) {
    if (member.is_owner) return '<span class="badge badge-primary badge-sm whitespace-nowrap">소유자</span>';
    return member.is_active
      ? '<span class="badge badge-success badge-sm whitespace-nowrap">활성</span>'
      : '<span class="badge badge-ghost badge-sm whitespace-nowrap">종료</span>';
  }

  /* ---------- 1. 목록 ---------- */
  async function loadMembers() {
    const tableBody = getElement('member-table-body');
    try {
      const response = await apiFetch(API + '?t=' + Date.now());
      const responseBody = await readResponseBody(response);
      if (!response.ok) throw new Error(describeFailure(responseBody, '팀원 목록을 불러오지 못했어요'));
      isKeySecretConfigured = !!responseBody.is_key_secret_configured;
      getElement('member-key-secret-env-name').textContent = responseBody.key_secret_env_name || '-';
      getElement('member-key-secret-warning').hidden = isKeySecretConfigured;
      renderMembers(responseBody.members || []);
    } catch (error) {
      tableBody.innerHTML = '<tr><td colspan="5" class="text-center text-error py-6">' + escapeHtml(error.message) + '</td></tr>';
    }
  }

  function renderMembers(members) {
    memberById = {};
    members.forEach(function (member) { memberById[member.id] = member; });
    const tableBody = getElement('member-table-body');
    if (!members.length) {
      tableBody.innerHTML = '<tr><td colspan="5" class="text-center opacity-50 py-6">아직 팀원이 없어요. "팀원 추가"로 시작해 보세요.</td></tr>';
      return;
    }
    tableBody.innerHTML = members.map(renderMemberRow).join('');
    tableBody.querySelectorAll('[data-member-action]').forEach(function (button) {
      button.addEventListener('click', function () {
        const member = memberById[button.dataset.memberId];
        if (member) onMemberAction(button.dataset.memberAction, member, button);
      });
    });
    if (window.lucide) lucide.createIcons();
  }

  function renderMemberRow(member) {
    const actionButton = function (action, icon, label, buttonClass) {
      return '<button class="btn btn-xs whitespace-nowrap ' + buttonClass + '" data-member-action="' + action +
        '" data-member-id="' + member.id + '"><i data-lucide="' + icon + '" class="size-3"></i>' + label + '</button>';
    };
    const buttons = [actionButton('expand', 'chevrons-down', '키 보기', 'btn-ghost')];
    if (member.is_active) {
      buttons.push(actionButton('issue', 'key-round', '키 발급', 'btn-primary btn-outline'));
      buttons.push(actionButton('link', 'link', '기존 토큰 연결', 'btn-ghost'));
      buttons.push(actionButton('edit', 'pencil', '수정', 'btn-ghost'));
      if (!member.is_owner) buttons.push(actionButton('end', 'user-x', '종료', 'btn-error btn-outline'));
    }
    const brains = member.brains.length ? ' (' + member.brains.map(escapeHtml).join(', ') + ')' : '';
    return '<tr class="' + (member.is_active ? '' : 'opacity-50') + '">' +
      '<td><div class="font-semibold">' + escapeHtml(member.display_name) + '</div>' +
      '<div class="font-mono text-[10px] opacity-50">' + escapeHtml(member.handle) + '</div></td>' +
      '<td class="text-xs"><div>' + escapeHtml(member.contact || '-') + '</div>' +
      '<div class="opacity-60 break-all">' + escapeHtml(member.memo || '') + '</div></td>' +
      '<td>' + describeMemberStatus(member) + '</td>' +
      '<td class="text-xs whitespace-nowrap">' + member.active_key_count + '개' + brains + '</td>' +
      '<td class="text-right"><div class="flex flex-wrap justify-end gap-1">' + buttons.join('') + '</div></td>' +
      '</tr>' +
      '<tr data-member-keys-row="' + member.id + '" hidden><td colspan="5" class="bg-base-200"></td></tr>';
  }

  function onMemberAction(action, member, button) {
    if (action === 'edit') return openMemberForm(member);
    if (action === 'end') return endMember(member, button);
    const memberKeys = window.gbrainMemberKeys;
    if (action === 'expand') return memberKeys.toggle(member);
    if (action === 'issue') return memberKeys.openIssue(member, isKeySecretConfigured);
    if (action === 'link') return memberKeys.openLink(member);
  }

  /* ---------- 2. 추가·수정 ---------- */
  function openMemberForm(member) {
    getElement('member-form').reset();
    const isEditing = !!member;
    getElement('member-form-title').textContent = isEditing ? member.display_name + ' 수정' : '팀원 추가';
    getElement('member-handle').value = isEditing ? member.handle : '';
    getElement('member-handle').disabled = isEditing;
    getElement('member-display-name').value = isEditing ? member.display_name : '';
    getElement('member-contact').value = isEditing ? member.contact : '';
    getElement('member-memo').value = isEditing ? member.memo : '';
    getElement('member-form-modal').dataset.memberId = isEditing ? member.id : '';
    getElement('member-form-error').hidden = true;
    getElement('member-form-modal').showModal();
  }

  async function submitMemberForm(event) {
    event.preventDefault();
    const memberId = getElement('member-form-modal').dataset.memberId;
    const errorText = getElement('member-form-error');
    const fields = {
      display_name: getElement('member-display-name').value.trim(),
      contact: getElement('member-contact').value.trim(), memo: getElement('member-memo').value.trim(),
    };
    if (!memberId) fields.handle = getElement('member-handle').value.trim();
    getElement('member-form-submit').disabled = true;
    try {
      const response = await apiFetch(memberId ? API + '/' + memberId : API,
        { method: memberId ? 'PUT' : 'POST', body: JSON.stringify(fields) });
      const responseBody = await readResponseBody(response);
      if (!response.ok) throw new Error(describeFailure(responseBody, '팀원을 저장하지 못했어요'));
      getElement('member-form-modal').close();
      showToast(responseBody.member.display_name + ' 팀원을 저장했어요', 'success');
      loadMembers();
    } catch (error) {
      errorText.textContent = error.message;
      errorText.hidden = false;
    } finally {
      getElement('member-form-submit').disabled = false;
    }
  }

  /* ---------- 3. 종료 (키 일괄 폐기) ---------- */
  async function endMember(member, button) {
    const confirmText = member.display_name + ' 팀원을 종료할까요?\n\n살아 있는 키 ' + member.active_key_count +
      '개를 gbrain 에서 모두 폐기해서 그 사람의 연결이 바로 끊겨요. 되돌릴 수 없어요.';
    if (!window.confirm(confirmText)) return;
    button.disabled = true;
    try {
      const response = await apiFetch(API + '/' + member.id + '/end', { method: 'POST' });
      const responseBody = await readResponseBody(response);
      if (!response.ok) throw new Error(describeFailure(responseBody, '팀원을 종료하지 못했어요'));
      showToast(member.display_name + ' 팀원을 종료하고 키 ' + responseBody.revoked_key_ids.length + '개를 폐기했어요', 'success');
    } catch (error) {
      showToast(escapeHtml(error.message), 'error');
    } finally {
      loadMembers();
    }
  }

  window.gbrainMembers = { reload: loadMembers };

  document.addEventListener('DOMContentLoaded', function () {
    loadMembers();
    getElement('member-refresh').addEventListener('click', loadMembers);
    getElement('member-create-open').addEventListener('click', function () { openMemberForm(null); });
    getElement('member-form').addEventListener('submit', submitMemberForm);
    document.querySelectorAll('[data-close-member-modal]').forEach(function (button) {
      button.addEventListener('click', function () { getElement(button.dataset.closeMemberModal).close(); });
    });
  });
})();
