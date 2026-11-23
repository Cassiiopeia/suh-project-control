/* gbrain 팀원 카드 (#221): 팀원 목록 > 추가·수정 > 종료(확인 창 > 키 일괄 폐기), 펼치기는 gbrain-member-keys.js
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
    const memberList = getElement('member-list');
    try {
      const response = await apiFetch(API + '?t=' + Date.now());
      const responseBody = await readResponseBody(response);
      if (!response.ok) throw new Error(describeFailure(responseBody, '팀원 목록을 불러오지 못했어요'));
      isKeySecretConfigured = !!responseBody.is_key_secret_configured;
      getElement('member-key-secret-env-name').textContent = responseBody.key_secret_env_name || '-';
      getElement('member-key-secret-warning').hidden = isKeySecretConfigured;
      renderMembers(responseBody.members || []);
    } catch (error) {
      memberList.innerHTML = '<li class="text-center text-sm text-error py-6">' + escapeHtml(error.message) + '</li>';
    }
  }

  function renderMembers(members) {
    memberById = {};
    members.forEach(function (member) { memberById[member.id] = member; });
    const memberList = getElement('member-list');
    if (!members.length) {
      memberList.innerHTML = '<li class="text-center text-sm opacity-60 py-6">아직 팀원이 없어요. "팀원 추가"로 시작해 보세요.</li>';
      return;
    }
    memberList.innerHTML = members.map(renderMemberItem).join('');
    memberList.querySelectorAll('[data-member-action]').forEach(function (button) {
      button.addEventListener('click', function () {
        if (button.closest('.dropdown')) document.activeElement.blur();  // 더보기 메뉴 닫기
        runMemberAction(button.dataset.memberAction, Number(button.dataset.memberId), button);
      });
    });
    if (window.lucide) lucide.createIcons();
  }

  // 팀원 1명: 이름·상태 > 연락처·메모 > 사용 중인 키 > 관리 버튼 (좁은 화면은 세로로 쌓임) + 펼치는 키 목록
  function renderMemberItem(member) {
    const contactLine = [member.contact, member.memo].filter(Boolean).map(escapeHtml).join(' · ');
    const brainLine = member.brains.length ? member.brains.map(escapeHtml).join(', ') : '';
    return '<li data-member-item="' + member.id + '" class="py-3">' +
      '<div class="flex flex-col gap-2 md:flex-row md:items-center md:gap-4' + (member.is_active ? '' : ' opacity-60') + '">' +
      '<div class="flex-1 min-w-0">' +
      '<div class="flex flex-wrap items-center gap-2"><span class="font-semibold">' + escapeHtml(member.display_name) + '</span>' +
      describeMemberStatus(member) + '<span class="font-mono text-xs opacity-50">' + escapeHtml(member.handle) + '</span></div>' +
      (contactLine ? '<div class="text-xs opacity-70 break-all mt-1">' + contactLine + '</div>' : '') +
      '</div>' +
      '<div class="text-xs md:w-44 shrink-0"><span class="opacity-60">사용 중인 키</span> <span class="font-semibold">' +
      member.active_key_count + '개</span>' + (brainLine ? '<div class="opacity-60 break-all">' + brainLine + '</div>' : '') + '</div>' +
      '<div class="flex flex-wrap items-center gap-1 md:justify-end shrink-0">' + renderMemberButtons(member) + '</div>' +
      '</div>' +
      '<div data-member-keys-panel="' + member.id + '" class="mt-3 bg-base-200 rounded-box px-3" hidden></div>' +
      '</li>';
  }

  // 버튼 순서: 키 발급(주 작업) > 키 목록 펼치기 > 더보기(기존 토큰 연결·정보 수정·종료), 종료한 팀원은 키 목록만
  function renderMemberButtons(member) {
    const buttons = [];
    if (member.is_active) {
      buttons.push(renderActionButton(member, 'issue', 'key-round', '키 발급', 'btn-primary btn-outline'));
    }
    buttons.push('<button class="btn btn-ghost btn-xs whitespace-nowrap" data-member-action="expand" data-member-id="' +
      member.id + '" aria-expanded="false"><i data-lucide="chevron-down" class="size-3"></i>키 목록</button>');
    if (member.is_active) {
      const menuItems = [
        renderMenuItem(member, 'link', 'link', '기존 토큰 연결', ''),
        renderMenuItem(member, 'edit', 'pencil', '정보 수정', ''),
      ];
      if (!member.is_owner) menuItems.push(renderMenuItem(member, 'end', 'user-x', '팀원 종료', 'text-error'));
      buttons.push('<div class="dropdown dropdown-end">' +
        '<div tabindex="0" role="button" class="btn btn-ghost btn-xs btn-square" aria-label="' + escapeHtml(member.display_name) +
        ' 더보기" title="더보기"><i data-lucide="ellipsis" class="size-4"></i></div>' +
        '<ul tabindex="0" class="dropdown-content menu menu-sm z-10 w-44 p-1 mt-1 rounded-box border border-base-300 bg-base-100 shadow">' +
        menuItems.join('') + '</ul></div>');
    }
    return buttons.join('');
  }

  function renderActionButton(member, action, icon, label, buttonClass) {
    return '<button class="btn btn-xs whitespace-nowrap ' + buttonClass + '" data-member-action="' + action +
      '" data-member-id="' + member.id + '"><i data-lucide="' + icon + '" class="size-3"></i>' + label + '</button>';
  }

  function renderMenuItem(member, action, icon, label, textClass) {
    return '<li><button class="' + textClass + '" data-member-action="' + action + '" data-member-id="' + member.id +
      '"><i data-lucide="' + icon + '" class="size-4"></i>' + label + '</button></li>';
  }

  // 목록 버튼·키 목록 빈 화면 버튼 공용 진입점
  function runMemberAction(action, memberId, button) {
    const member = memberById[memberId];
    if (!member) return;
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
    const isConfirmed = await window.gbrainPage.confirmDanger({
      title: member.display_name + ' 팀원을 종료할까요?',
      consequences: [
        member.active_key_count ? '사용 중인 키 ' + member.active_key_count + '개를 gbrain 에서 모두 폐기해요.' : '사용 중인 키는 없어요.',
        '그 팀원의 브레인 연결이 바로 끊겨요.',
        '종료는 되돌릴 수 없어요. 다시 함께하면 새 영문 id 로 추가해 주세요.',
      ],
      confirmLabel: member.active_key_count ? '종료하고 키 ' + member.active_key_count + '개 폐기' : '종료',
    });
    if (!isConfirmed) return;
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

  window.gbrainMembers = {
    reload: loadMembers, runAction: runMemberAction,
    find: function (memberId) { return memberById[memberId]; },
  };

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
