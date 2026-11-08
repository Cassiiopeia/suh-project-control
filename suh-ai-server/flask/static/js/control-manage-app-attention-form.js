/* 앱 연동 소스 추가·수정 창: 칸 채우기 > 토큰 이름·push 입구 안내 > 저장 (추가 POST 전체, 수정 PATCH 바뀐 칸만) > 칸별 오류 표시
   window.ControlManageAppAttentionForm.open(projects, source|null) */
(function () {
  const SOURCES_PATH = '/app-attention/sources';
  const PULL_MODE = 'pull';
  const PUSH_MODE = 'push';
  // 서버 칸 이름 > 입력 요소 id
  const FIELD_INPUT_IDS = {
    project_id: 'control-attention-source-project', source_id: 'control-attention-source-id',
    mode: 'control-attention-source-mode', url: 'control-attention-source-url',
    interval_seconds: 'control-attention-source-interval', timeout_seconds: 'control-attention-source-timeout',
    stale_after_seconds: 'control-attention-source-stale', is_enabled: 'control-attention-source-enabled',
  };
  // 수정 시 PATCH 가능한 칸 (project_id·source_id는 바꿀 수 없음)
  const EDITABLE_FIELDS = ['url', 'is_enabled', 'mode', 'interval_seconds', 'timeout_seconds', 'stale_after_seconds'];
  const NUMBER_FIELDS = ['interval_seconds', 'timeout_seconds', 'stale_after_seconds'];
  // 오류 코드 > 표시할 칸 (fields 없는 오류)
  const ERROR_FIELD_BY_CODE = { source_exists: 'source_id', unknown_project: 'project_id' };
  const actions = window.ControlManageActions;
  const controlFormat = window.ControlFormat;
  const attentionFormat = window.AppAttentionFormat;
  const createElement = controlFormat.createElement;

  let editingSource = null;  // null이면 추가
  let initialValues = {};

  function findElement(id) { return document.getElementById(id); }
  function inputOf(field) { return findElement(FIELD_INPUT_IDS[field]); }

  /* ---------- 1. 열기 ---------- */
  function open(projects, source) {
    editingSource = source;
    findElement('control-attention-source-title').textContent = source
      ? '소스 수정 · ' + source.project_name + ' / ' + source.source_id : '소스 추가';
    fillProjectSelect(projects, source);
    fillModeSelect();
    setValues(source ? {
      project_id: source.project_id, source_id: source.source_id, mode: source.mode, url: source.url || '',
      interval_seconds: source.interval_seconds, timeout_seconds: source.timeout_seconds,
      stale_after_seconds: source.stale_after_seconds, is_enabled: source.is_enabled,
    } : {
      project_id: projects.length ? projects[0].id : '', source_id: '', mode: PULL_MODE, url: '',
      interval_seconds: '', timeout_seconds: '', stale_after_seconds: '', is_enabled: true,
    });
    inputOf('project_id').disabled = !!source;
    inputOf('source_id').disabled = !!source;
    initialValues = readValues();
    clearErrors();
    renderHelp();
    findElement('control-attention-source-modal').showModal();
  }

  function fillProjectSelect(projects, source) {
    const select = inputOf('project_id');
    select.replaceChildren();
    const options = projects.map(function (project) { return { value: project.id, label: project.name + ' (' + project.id + ')' }; });
    // 관리 목록에 없는 프로젝트 소스도 수정 가능하게
    if (source && !options.some(function (option) { return option.value === source.project_id; })) {
      options.push({ value: source.project_id, label: source.project_name + ' (' + source.project_id + ')' });
    }
    options.forEach(function (option) { select.appendChild(createOption(option)); });
  }

  function fillModeSelect() {
    const select = inputOf('mode');
    if (select.options.length) return;
    attentionFormat.MODE_OPTIONS.forEach(function (option) { select.appendChild(createOption(option)); });
  }

  function createOption(option) {
    const element = createElement('option', '', option.label);
    element.value = option.value;
    return element;
  }

  /* ---------- 2. 값 읽기·쓰기 ---------- */
  function setValues(values) {
    Object.keys(FIELD_INPUT_IDS).forEach(function (field) {
      const input = inputOf(field);
      if (field === 'is_enabled') input.checked = !!values[field];
      else input.value = values[field] === null || values[field] === undefined ? '' : values[field];
    });
  }

  // 입력값 > 서버 값 (빈 숫자·주소는 null, 숫자는 Number)
  function readValues() {
    const values = {};
    Object.keys(FIELD_INPUT_IDS).forEach(function (field) {
      const input = inputOf(field);
      if (field === 'is_enabled') { values[field] = input.checked; return; }
      const text = input.value.trim();
      if (NUMBER_FIELDS.indexOf(field) >= 0) values[field] = text === '' ? null : Number(text);
      else values[field] = text === '' ? null : text;
    });
    return values;
  }

  // 추가: 빈 칸은 빼서 서버 기본값 / 수정: 처음 값과 다른 칸만 (빈 값 = null로 기본값 복귀)
  function buildPayload(values) {
    if (!editingSource) {
      const payload = {};
      Object.keys(values).forEach(function (field) { if (values[field] !== null) payload[field] = values[field]; });
      return payload;
    }
    const changes = {};
    EDITABLE_FIELDS.forEach(function (field) { if (values[field] !== initialValues[field]) changes[field] = values[field]; });
    return changes;
  }

  /* ---------- 3. 안내 (토큰 이름·push 입구, 값은 표시 안 함) ---------- */
  function renderHelp() {
    const values = readValues();
    const projectId = values.project_id;
    const sourceId = values.source_id;
    const help = findElement('control-attention-source-help');
    help.replaceChildren();
    if (values.mode !== PUSH_MODE) {
      appendHelpLine(help, '가져오기: 관제소가 위 주소로 GET, 헤더 ' + attentionFormat.TOKEN_HEADER_NAME + ' = 서버 .env ',
        attentionFormat.pullTokenEnvName(projectId, sourceId));
    }
    if (values.mode !== PULL_MODE) {
      appendHelpLine(help, '앱이 보냄: POST ' + attentionFormat.pushIntakeUrl(projectId, sourceId) + ', 헤더 '
        + attentionFormat.TOKEN_HEADER_NAME + ' = 서버 .env ', attentionFormat.eventTokenEnvName(projectId));
    }
    help.appendChild(createElement('div', 'opacity-60', '토큰 교체 중에는 이름 뒤에 _PREVIOUS를 붙인 이전 값도 받습니다. 앱 쪽에도 같은 값을 넣으세요.'));
  }

  function appendHelpLine(container, text, envName) {
    const line = createElement('div', '', text);
    line.appendChild(createElement('span', 'font-mono font-semibold', envName));
    container.appendChild(line);
  }

  /* ---------- 4. 오류 표시 ---------- */
  function clearErrors() {
    document.querySelectorAll('#control-attention-source-form [data-field-error]').forEach(function (element) { element.hidden = true; });
    Object.keys(FIELD_INPUT_IDS).forEach(function (field) { inputOf(field).classList.remove('input-error', 'select-error'); });
    findElement('control-attention-source-error').hidden = true;
  }

  function showFieldErrors(fields) {
    fields.forEach(function (field) {
      const message = document.querySelector('#control-attention-source-form [data-field-error="' + field + '"]');
      if (message) message.hidden = false;
      const input = FIELD_INPUT_IDS[field] ? inputOf(field) : null;
      if (input) input.classList.add(input.tagName === 'SELECT' ? 'select-error' : 'input-error');
    });
  }

  function showFormError(text) {
    const error = findElement('control-attention-source-error');
    error.textContent = text;
    error.hidden = false;
  }

  /* ---------- 5. 저장 ---------- */
  async function save() {
    clearErrors();
    const payload = buildPayload(readValues());
    if (editingSource && !Object.keys(payload).length) { showToast('바뀐 값이 없습니다', 'info'); return; }
    const button = findElement('control-attention-source-save');
    button.disabled = true;
    try {
      const result = editingSource
        ? await actions.sendJson('PATCH', window.ControlManageAppAttention.sourcePath(editingSource), payload)
        : await actions.sendJson('POST', SOURCES_PATH, payload);
      if (!result.ok) { showSaveFailure(result); return; }
      showToast(editingSource ? '소스를 저장했습니다' : '소스를 추가했습니다', 'success');
      findElement('control-attention-source-modal').close();
      window.ControlManageAppAttention.notifyChanged();
    } catch (error) {
      console.warn('control app attention source save failed:', error);
      showFormError('요청에 실패했습니다');
    } finally {
      button.disabled = false;
    }
  }

  function showSaveFailure(result) {
    const fields = result.data.fields || (ERROR_FIELD_BY_CODE[result.data.error] ? [ERROR_FIELD_BY_CODE[result.data.error]] : []);
    showFieldErrors(fields);
    // 칸 오류는 칸 아래 안내로 충분 (그 외 오류만 문구)
    showFormError(result.data.error === 'invalid' && fields.length ? '빨간 칸을 확인하세요' : attentionFormat.describeApiFailure(result));
  }

  /* ---------- 6. 시작 ---------- */
  ['project_id', 'source_id', 'mode'].forEach(function (field) { inputOf(field).addEventListener('input', renderHelp); });
  findElement('control-attention-source-form').addEventListener('submit', function (event) { event.preventDefault(); save(); });
  findElement('control-attention-source-save').addEventListener('click', save);
  window.ControlManageAppAttentionForm = { open: open };
})();
