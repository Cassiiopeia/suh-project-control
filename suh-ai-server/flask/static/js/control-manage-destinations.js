/* 관제소 프로젝트 카드의 "추가로 받을 곳" 접이식 영역: 받을 곳 표(종류·이름·수단·사용·최근 결과·테스트·삭제) + 추가 폼
   POST /control/projects/{id}/destinations, PATCH·DELETE /control/destinations/{id}, POST .../{id}/test > ControlManage.reload()
   window.ControlManageDestinations 로 노출, 종류 선택지·입력 길이·결과 문구·비밀값 설정 여부는 GET /control/manage 값 사용 (URL 원문은 응답에 없음) */
(function () {
  const actions = window.ControlManageActions;
  const controlFormat = window.ControlFormat;
  const createElement = controlFormat.createElement;
  const DESTINATION_COLUMNS = ['종류', '이름', '수단', '사용', '최근 결과', ''];
  // 칸 이름 > 표시 이름 (400 fields 안내용)
  const FIELD_LABELS = { kind: '종류', label: '이름', url: 'URL (해석할 수 없는 형식)', is_enabled: '사용' };
  const NO_RESULT_LABEL = '아직 없음';
  // URL 예시: Apprise 형식 (수단://값)
  const URL_EXAMPLES = ['discord://웹훅ID/웹훅토큰', 'slack://토큰A/토큰B/토큰C', 'tgram://봇토큰/채팅ID', 'mailto://계정:비밀번호@메일서버'];
  const DELETE_CONFIRM_SUFFIX = ' 받을 곳을 삭제할까요?';
  // 비밀값 없음 안내 = 409 secret_not_configured 문구 (ControlManageActions 오류 문구 원본 사용)
  const SECRET_MISSING_TEXT = actions.describeFailure({ status: 409, data: { error: 'secret_not_configured' } }) +
    ' (받을 곳 추가·사용 켜기·테스트 불가, 끄기·삭제는 가능)';

  // 다시 그려도 펼친 상태 유지 (프로젝트 id 기준)
  const expandedProjectIds = new Set();

  // 결과 코드 > 표시 문구 (options = destination_options: result_labels, error:* 는 오류 문구 + 예외 이름)
  function describeResult(resultCode, options) {
    if (!resultCode) return NO_RESULT_LABEL;
    if (options.result_labels[resultCode]) return options.result_labels[resultCode];
    const errorPrefix = options.error_result_prefix;
    if (resultCode.indexOf(errorPrefix) === 0) return options.error_result_label + ' (' + resultCode.slice(errorPrefix.length) + ')';
    return resultCode;
  }

  function describeFailure(result) {
    if (result.data.error !== 'invalid') return actions.describeFailure(result);
    const fields = (result.data.fields || []).map(function (field) { return FIELD_LABELS[field] || field; });
    return '입력값을 확인하세요' + (fields.length ? ' : ' + fields.join(', ') : '');
  }

  // 요청 1건: 실패 안내 > 성공 처리 > 목록 재조회 (실패해도 재조회로 화면 값 되돌림)
  async function requestDestination(method, path, payload, onSuccess) {
    try {
      const result = await actions.sendJson(method, path, payload);
      if (!result.ok) showToast(describeFailure(result), 'error');
      else onSuccess(result.data);
      if (window.ControlManage) window.ControlManage.reload();
      return result.ok;
    } catch (error) {
      console.warn('control destination request failed:', error && error.name);  // URL은 콘솔에 남기지 않음
      showToast('요청에 실패했습니다', 'error');
      return false;
    }
  }

  function destinationPath(destinationId) {
    return '/destinations/' + encodeURIComponent(destinationId);
  }

  function createIconButton(iconName, title, ariaLabel, isEnabled, onClick) {
    const button = createElement('button', 'btn btn-ghost btn-xs');
    button.type = 'button';
    button.title = title;
    button.disabled = !isEnabled;
    button.setAttribute('aria-label', ariaLabel);
    const icon = createElement('i', 'size-4');
    icon.setAttribute('data-lucide', iconName);
    button.appendChild(icon);
    button.addEventListener('click', async function () {
      button.disabled = true;
      await onClick();
      button.disabled = false;
    });
    return button;
  }

  /* ---------- 1. 받을 곳 표 ---------- */
  function createDestinationTable(project, options, isSecretConfigured) {
    const wrapper = createElement('div', 'overflow-x-auto');
    const table = createElement('table', 'table table-xs');
    const headRow = createElement('tr');
    DESTINATION_COLUMNS.forEach(function (label) { headRow.appendChild(createElement('th', '', label)); });
    table.appendChild(createElement('thead')).appendChild(headRow);
    const tableBody = createElement('tbody');
    if (!project.destinations.length) tableBody.appendChild(controlFormat.createEmptyRow(DESTINATION_COLUMNS.length, '추가한 받을 곳 없음 (SUH 관제소 디스코드만 사용)'));
    project.destinations.forEach(function (destination) {
      tableBody.appendChild(createDestinationRow(destination, options, isSecretConfigured));
    });
    table.appendChild(tableBody);
    wrapper.appendChild(table);
    return wrapper;
  }

  function createEnabledToggle(destination, isSecretConfigured) {
    const toggle = createElement('input', 'toggle toggle-xs toggle-success');
    toggle.type = 'checkbox';
    toggle.checked = destination.is_enabled;
    toggle.disabled = !isSecretConfigured && !destination.is_enabled;  // 끄기는 비밀값 없어도 가능 (켜기만 막음)
    toggle.setAttribute('aria-label', destination.label + ' 사용');
    toggle.addEventListener('change', function () {
      toggle.disabled = true;
      requestDestination('PATCH', destinationPath(destination.destination_id), { is_enabled: toggle.checked }, function () {
        showToast(toggle.checked ? '받을 곳을 사용합니다' : '받을 곳을 중지했습니다', 'success');
      });
    });
    return toggle;
  }

  // 최근 결과 칸: 결과 문구 + 최근 시도 시각 (성공·실패 모두 시도로 기록됨)
  function createResultCell(destination, options) {
    const cell = createElement('td');
    cell.appendChild(createElement('div', '', describeResult(destination.last_result, options)));
    if (destination.last_sent_at) {
      cell.appendChild(createElement('div', 'text-xs opacity-60', '최근 시도 ' + controlFormat.formatDateTime(destination.last_sent_at)));
    }
    return cell;
  }

  function createDestinationRow(destination, options, isSecretConfigured) {
    const row = createElement('tr', destination.is_enabled ? '' : 'opacity-60');
    row.appendChild(controlFormat.createCell(destination.kind, 'font-mono'));
    row.appendChild(controlFormat.createCell(destination.label));
    row.appendChild(controlFormat.createCell(destination.url_hint, 'font-mono'));
    row.appendChild(controlFormat.createCell(createEnabledToggle(destination, isSecretConfigured)));
    row.appendChild(createResultCell(destination, options));
    const buttonCell = createElement('td', 'whitespace-nowrap');
    buttonCell.appendChild(createIconButton('send', '테스트 발송', destination.label + ' 테스트 발송', isSecretConfigured, function () {
      return requestDestination('POST', destinationPath(destination.destination_id) + '/test', undefined, function (data) {
        showToast('테스트 발송 결과: ' + describeResult(data.result, options), data.is_sent ? 'success' : 'error');
      });
    }));
    // 삭제는 비밀값 없어도 가능
    buttonCell.appendChild(createIconButton('trash-2', '삭제', destination.label + ' 받을 곳 삭제', true, async function () {
      if (!confirm(destination.label + DELETE_CONFIRM_SUFFIX)) return;
      await requestDestination('DELETE', destinationPath(destination.destination_id), undefined, function () {
        showToast('받을 곳을 삭제했습니다', 'success');
      });
    }));
    row.appendChild(buttonCell);
    return row;
  }

  /* ---------- 2. 추가 폼 ---------- */
  function createKindSelect(project) {
    const select = createElement('select', 'select select-xs w-36 font-mono');
    select.setAttribute('aria-label', project.name + ' 받을 곳 종류');
    project.destination_kinds.forEach(function (kind) {
      const option = createElement('option', '', kind);
      option.value = kind;
      select.appendChild(option);
    });
    return select;
  }

  function createTextInput(className, placeholder, ariaLabel, maxLength, inputType) {
    const input = createElement('input', 'input input-xs ' + className);
    input.type = inputType || 'text';
    input.autocomplete = 'off';
    input.spellcheck = false;
    input.required = true;
    input.placeholder = placeholder;
    input.maxLength = maxLength;
    input.setAttribute('aria-label', ariaLabel);
    return input;
  }

  // options: GET /control/manage 의 destination_options (서버 검증 길이 원본)
  function createAddForm(project, options, isSecretConfigured) {
    const form = createElement('form', 'flex flex-wrap items-center gap-2 mt-2');
    const kindSelect = createKindSelect(project);
    const labelInput = createTextInput('w-36', '이름 (예: 팀 디스코드)', project.name + ' 받을 곳 이름', options.label_max_length);
    const urlInput = createTextInput('w-72 font-mono', URL_EXAMPLES[0], project.name + ' 받을 곳 URL', options.url_max_length, 'password');  // URL = 비밀 토큰 포함 > 화면 가림 (autocomplete off 는 createTextInput 공통)
    const submitButton = createElement('button', 'btn btn-outline btn-xs', '받을 곳 추가');
    submitButton.type = 'submit';
    [kindSelect, labelInput, urlInput, submitButton].forEach(function (element) {
      element.disabled = !isSecretConfigured;
      form.appendChild(element);
    });

    form.addEventListener('submit', async function (event) {
      event.preventDefault();
      const payload = { kind: kindSelect.value, label: labelInput.value.trim(), url: urlInput.value.trim() };
      submitButton.disabled = true;
      await requestDestination('POST', '/projects/' + encodeURIComponent(project.id) + '/destinations', payload, function () {
        urlInput.value = '';  // URL 원문은 화면에 남기지 않음
        showToast('받을 곳을 추가했습니다', 'success');
      });
      submitButton.disabled = false;
    });
    return form;
  }

  function createUrlExampleLine() {
    return createElement('div', 'text-xs opacity-60 mt-1 font-mono', 'URL 예시: ' + URL_EXAMPLES.join('  ·  '));
  }

  /* ---------- 3. 접이식 영역 ---------- */
  function createDestinationSection(project, manageData) {
    const isSecretConfigured = manageData.is_token_secret_configured;
    const details = createElement('details', 'mt-2 text-sm');
    details.open = expandedProjectIds.has(project.id);
    details.addEventListener('toggle', function () {
      if (details.open) expandedProjectIds.add(project.id); else expandedProjectIds.delete(project.id);
    });
    details.appendChild(createElement('summary', 'cursor-pointer text-xs opacity-70',
      '추가로 받을 곳 ' + project.destinations.length + '개 · 팀 디스코드·슬랙·텔레그램·메일로도 같은 알림 받기'));
    details.appendChild(createDestinationTable(project, manageData.destination_options, isSecretConfigured));
    details.appendChild(createAddForm(project, manageData.destination_options, isSecretConfigured));
    details.appendChild(createUrlExampleLine());
    if (!isSecretConfigured) details.appendChild(createElement('div', 'text-xs text-warning mt-1', SECRET_MISSING_TEXT));
    return details;
  }

  window.ControlManageDestinations = { createDestinationSection: createDestinationSection };
})();
