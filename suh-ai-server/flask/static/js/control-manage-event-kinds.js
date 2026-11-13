/* 관제소 프로젝트 카드의 "알림 종류" 접이식 영역: 종류 표(종류·채널 이름·공개 대상·삭제) + 추가 폼
   POST·DELETE /control/projects/{id}/event-kinds > 성공 시 ControlManage.reload() / window.ControlManageEventKinds 로 노출
   공개 대상 선택지·기본값은 GET /control/manage 의 event_kind_options (서버 검증과 같은 원본) */
(function () {
  const actions = window.ControlManageActions;
  const controlFormat = window.ControlFormat;
  const createElement = controlFormat.createElement;
  const KIND_COLUMNS = ['종류', '채널 이름', '공개 대상', ''];
  // 역할 키 > 표시 이름 (모르는 키는 키 그대로 표시)
  const ROLE_LABELS = { dev: '개발자', member: '멤버' };
  const ADMIN_ONLY_LABEL = '관리자만';
  // 종류 이름 규칙 (서버 검증과 같음): 소문자로 시작, 소문자·숫자·하이픈 2~32자
  const KIND_INPUT_PATTERN = '[a-z][a-z0-9\\-]{1,31}';
  const CHANNEL_NAME_MAX_LENGTH = 40;
  // 400 invalid 안내 (그 외 코드는 ControlManageActions.describeFailure 공통 문구)
  const INVALID_MESSAGE = '입력값을 확인하세요 (종류: 소문자로 시작, 소문자·숫자·- 2~32자, 기본 채널 종류 이름 불가)';
  // 칸 이름 > 표시 이름 (400 fields 안내용)
  const FIELD_LABELS = { kind: '종류', channel_name: '채널 이름', visible_to: '공개 대상' };
  const DELETE_CONFIRM_SUFFIX = ' 종류를 삭제할까요? 디스코드 채널은 지우지 않고 관리자만 보이게 보관합니다.';
  const SYNC_NOTICE = ' (디스코드 채널은 잠시 뒤 반영됩니다)';

  // 다시 그려도 펼친 상태 유지 (프로젝트 id 기준)
  const expandedProjectIds = new Set();

  function describeFailure(result) {
    if (result.data.error !== 'invalid') return actions.describeFailure(result);
    const fields = (result.data.fields || []).map(function (field) { return FIELD_LABELS[field] || field; });
    return INVALID_MESSAGE + (fields.length ? ' : ' + fields.join(', ') : '');
  }

  // 요청 1건: 실패 안내 > 성공 문구 > 목록 재조회
  async function requestEventKind(method, path, payload, successMessage) {
    try {
      const result = await actions.sendJson(method, path, payload);
      if (!result.ok) { showToast(describeFailure(result), 'error'); return false; }
      showToast(successMessage + SYNC_NOTICE, 'success');
      if (window.ControlManage) window.ControlManage.reload();
      return true;
    } catch (error) {
      console.warn('control event kind request failed:', error);
      showToast('요청에 실패했습니다', 'error');
      return false;
    }
  }

  function eventKindsPath(projectId) {
    return '/projects/' + encodeURIComponent(projectId) + '/event-kinds';
  }

  function describeVisibleTo(visibleTo) {
    if (!visibleTo.length) return ADMIN_ONLY_LABEL;
    return visibleTo.map(function (roleKey) { return ROLE_LABELS[roleKey] || roleKey; }).join(', ') + ' (+ 관리자)';
  }

  /* ---------- 1. 종류 표 ---------- */
  function createKindTable(project) {
    const wrapper = createElement('div', 'overflow-x-auto');
    const table = createElement('table', 'table table-xs');
    const headRow = createElement('tr');
    KIND_COLUMNS.forEach(function (label) { headRow.appendChild(createElement('th', '', label)); });
    table.appendChild(createElement('thead')).appendChild(headRow);
    const tableBody = createElement('tbody');
    if (!project.event_kinds.length) tableBody.appendChild(controlFormat.createEmptyRow(KIND_COLUMNS.length, '추가한 알림 종류 없음 (기본 채널만 사용)'));
    project.event_kinds.forEach(function (eventKind) { tableBody.appendChild(createKindRow(project, eventKind)); });
    table.appendChild(tableBody);
    wrapper.appendChild(table);
    return wrapper;
  }

  function createKindRow(project, eventKind) {
    const row = createElement('tr');
    row.appendChild(controlFormat.createCell(eventKind.kind, 'font-mono'));
    row.appendChild(controlFormat.createCell('#' + eventKind.channel_name));
    row.appendChild(controlFormat.createCell(describeVisibleTo(eventKind.visible_to)));
    const deleteButton = createElement('button', 'btn btn-ghost btn-xs');
    deleteButton.type = 'button';
    deleteButton.title = '삭제';
    deleteButton.setAttribute('aria-label', eventKind.kind + ' 종류 삭제');
    const icon = createElement('i', 'size-4');
    icon.setAttribute('data-lucide', 'trash-2');
    deleteButton.appendChild(icon);
    deleteButton.addEventListener('click', async function () {
      if (!confirm(eventKind.kind + DELETE_CONFIRM_SUFFIX)) return;
      deleteButton.disabled = true;
      const isDeleted = await requestEventKind('DELETE', eventKindsPath(project.id) + '/' + encodeURIComponent(eventKind.kind),
        undefined, '알림 종류를 삭제했습니다');
      if (!isDeleted) deleteButton.disabled = false;
    });
    row.appendChild(controlFormat.createCell(deleteButton));
    return row;
  }

  /* ---------- 2. 추가 폼 ---------- */
  function createTextInput(className, placeholder, ariaLabel) {
    const input = createElement('input', 'input input-xs ' + className);
    input.type = 'text';
    input.autocomplete = 'off';
    input.placeholder = placeholder;
    input.setAttribute('aria-label', ariaLabel);
    return input;
  }

  // 공개 대상 체크박스: 역할 키마다 1개 (기본값만 체크, 모두 끄면 관리자만)
  function createRoleCheckboxes(eventKindOptions) {
    const group = createElement('div', 'flex items-center gap-3');
    group.appendChild(createElement('span', 'text-xs opacity-70', '공개 대상'));
    const checkboxes = eventKindOptions.visible_role_keys.map(function (roleKey) {
      const label = createElement('label', 'label cursor-pointer gap-1 text-xs');
      const checkbox = createElement('input', 'checkbox checkbox-xs');
      checkbox.type = 'checkbox';
      checkbox.value = roleKey;
      checkbox.checked = eventKindOptions.default_visible_to.indexOf(roleKey) !== -1;
      label.appendChild(checkbox);
      label.appendChild(createElement('span', '', ROLE_LABELS[roleKey] || roleKey));
      group.appendChild(label);
      return checkbox;
    });
    group.appendChild(createElement('span', 'text-xs opacity-50', '모두 끄면 ' + ADMIN_ONLY_LABEL));
    return { element: group, checkboxes: checkboxes };
  }

  function createAddForm(project, eventKindOptions) {
    const form = createElement('form', 'flex flex-wrap items-center gap-2 mt-2');
    const kindInput = createTextInput('w-36 font-mono', 'claude-code', project.name + ' 새 알림 종류');
    kindInput.required = true;
    kindInput.pattern = KIND_INPUT_PATTERN;
    kindInput.title = '소문자로 시작, 소문자·숫자·- 2~32자';
    const channelNameInput = createTextInput('w-40', '채널 이름 (비우면 종류)', project.name + ' 새 알림 채널 이름');
    channelNameInput.maxLength = CHANNEL_NAME_MAX_LENGTH;
    const roleCheckboxes = createRoleCheckboxes(eventKindOptions);
    const submitButton = createElement('button', 'btn btn-outline btn-xs', '종류 추가');
    submitButton.type = 'submit';

    form.addEventListener('submit', async function (event) {
      event.preventDefault();
      const payload = {
        kind: kindInput.value.trim(),
        visible_to: roleCheckboxes.checkboxes.filter(function (checkbox) { return checkbox.checked; })
          .map(function (checkbox) { return checkbox.value; }),
      };
      const channelName = channelNameInput.value.trim();
      if (channelName) payload.channel_name = channelName;
      submitButton.disabled = true;
      await requestEventKind('POST', eventKindsPath(project.id), payload, '알림 종류를 추가했습니다');
      submitButton.disabled = false;
    });
    [kindInput, channelNameInput, roleCheckboxes.element, submitButton].forEach(function (element) { form.appendChild(element); });
    return form;
  }

  /* ---------- 3. 접이식 영역 ---------- */
  // eventKindOptions: GET /control/manage 의 event_kind_options ({visible_role_keys, default_visible_to})
  function createEventKindSection(project, eventKindOptions) {
    const details = createElement('details', 'mt-2 text-sm');
    details.open = expandedProjectIds.has(project.id);
    details.addEventListener('toggle', function () {
      if (details.open) expandedProjectIds.add(project.id); else expandedProjectIds.delete(project.id);
    });
    details.appendChild(createElement('summary', 'cursor-pointer text-xs opacity-70',
      '알림 종류 ' + project.event_kinds.length + '개 · 종류마다 이 프로젝트 전용 디스코드 채널 생성'));
    details.appendChild(createKindTable(project));
    details.appendChild(createAddForm(project, eventKindOptions));
    return details;
  }

  window.ControlManageEventKinds = { createEventKindSection: createEventKindSection };
})();
