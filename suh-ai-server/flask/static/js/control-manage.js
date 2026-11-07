/* 관제소 서비스 관리 탭: GET /control/manage > 프로젝트별 카드·서비스 표 렌더 / 추가 폼·DNS 가져오기 연결
   흐름: 탭 열림 > 조회 > 렌더 > (동작 후) ControlManage.reload() / 조회 결과는 'control-manage-loaded' 이벤트로 공유 */
(function () {
  const actions = window.ControlManageActions;
  const controlFormat = window.ControlFormat;
  const createElement = controlFormat.createElement;
  const INFRASTRUCTURE_LABEL = '인프라';
  const MOVE_UP = -1;
  const MOVE_DOWN = 1;
  // 추적 상태 선택지: active 추적함 / paused 감시만(알림 없음) / retired 추적 안 함
  const STATUS_OPTIONS = [
    { value: 'active', label: '추적함' }, { value: 'paused', label: '감시만' }, { value: 'retired', label: '추적 안 함' },
  ];
  const SERVICE_COLUMNS = ['이름', '상태', '추적', '공개', '순서', '주소', ''];

  let manageData = null;
  let dnsZoneName = '';

  function findElement(id) { return document.getElementById(id); }

  /* ---------- 1. 조회 ---------- */
  async function reload() {
    try {
      const result = await actions.sendJson('GET', '/manage');
      if (!result.ok) throw new Error('manage status ' + result.status);
      manageData = result.data;
      render();
      document.dispatchEvent(new CustomEvent('control-manage-loaded', { detail: manageData }));
    } catch (error) {
      console.warn('control manage failed:', error);
      findElement('control-manage-groups').replaceChildren(createElement('div', 'text-error text-sm', '목록을 불러오지 못했습니다'));
    }
  }

  /* ---------- 2. 렌더 ---------- */
  function render() {
    const usage = manageData.external_checks;
    findElement('control-manage-external-usage').textContent = '외부 점검 ' + usage.used + ' / ' + usage.maximum;
    const groups = findElement('control-manage-groups');
    groups.replaceChildren();
    manageData.projects.forEach(function (project, index) {
      groups.appendChild(createGroupCard(project, index, servicesOf(project.id)));
    });
    const infrastructure = servicesOf(null);
    if (infrastructure.length) groups.appendChild(createGroupCard(null, -1, infrastructure));
    fillProjectSelects();
    lucide.createIcons();
  }

  // 추적 중 > 추적 안 함 순 (각각 표시 순서 유지)
  function servicesOf(projectId) {
    const services = manageData.services.filter(function (service) { return service.project_id === projectId; });
    return services.filter(function (service) { return service.status !== 'retired'; })
      .concat(services.filter(function (service) { return service.status === 'retired'; }));
  }

  function createGroupCard(project, projectIndex, services) {
    const card = createElement('div', 'card bg-base-100 shadow border border-base-300' + (project && project.is_hidden ? ' opacity-80' : ''));
    const body = createElement('div', 'card-body p-4');
    body.appendChild(project ? createProjectHeader(project, projectIndex) : createElement('h3', 'font-semibold', INFRASTRUCTURE_LABEL));
    const tableWrapper = createElement('div', 'overflow-x-auto');
    const table = createElement('table', 'table table-sm');
    const headRow = createElement('tr');
    SERVICE_COLUMNS.forEach(function (label) { headRow.appendChild(createElement('th', '', label)); });
    table.appendChild(createElement('thead')).appendChild(headRow);
    const tableBody = createElement('tbody');
    if (!services.length) tableBody.appendChild(controlFormat.createEmptyRow(SERVICE_COLUMNS.length, '서비스 없음'));
    services.forEach(function (service, index) { tableBody.appendChild(createServiceRow(service, index, services)); });
    table.appendChild(tableBody);
    tableWrapper.appendChild(table);
    body.appendChild(tableWrapper);
    card.appendChild(body);
    return card;
  }

  // 프로젝트 머리: 이름 수정, 숨김, 초대 링크, 순서, 출처
  function createProjectHeader(project, projectIndex) {
    const header = createElement('div', 'flex flex-wrap items-center gap-2');
    header.appendChild(createNameInput(project.name, project.original_name, function (name) {
      actions.patchProject(project.id, { name: name });
    }, 'input-sm font-semibold w-48'));
    header.appendChild(createElement('span', 'font-mono text-xs opacity-60', project.id));
    header.appendChild(createSourceBadge(project.source, project.overridden_fields));
    const hiddenToggle = createToggle(!project.is_hidden, '공개 페이지에 표시', function (isChecked) {
      actions.patchProject(project.id, { is_hidden: !isChecked }, isChecked ? '프로젝트를 표시합니다' : '프로젝트를 숨겼습니다');
    });
    hiddenToggle.classList.add('ml-auto');
    header.appendChild(hiddenToggle);
    header.appendChild(window.ControlManageInvite.createInviteControl(project));
    header.appendChild(createMoveButtons(function (direction) {
      actions.moveItem('projects', manageData.projects, projectIndex, direction);
    }));
    return header;
  }

  function createServiceRow(service, index, services) {
    const row = createElement('tr', service.status === 'retired' ? 'opacity-50' : '');
    const nameCell = createElement('td');
    nameCell.appendChild(createNameInput(service.name, service.original.name, function (name) {
      actions.patchService(service.id, { name: name });
    }, 'input-xs w-40'));
    const idLine = createElement('div', 'flex items-center gap-1 mt-1');
    idLine.appendChild(createElement('span', 'font-mono text-xs opacity-60', service.id));
    idLine.appendChild(createSourceBadge(service.source, service.overridden_fields));
    nameCell.appendChild(idLine);
    row.appendChild(nameCell);
    row.appendChild(controlFormat.createCell(controlFormat.createStatusBadge({
      lifecycle: service.status, status: service.runtime_status, maintenance: null })));
    row.appendChild(controlFormat.createCell(createStatusSelect(service)));
    row.appendChild(controlFormat.createCell(createPublicToggle(service)));
    row.appendChild(controlFormat.createCell(createMoveButtons(function (direction) {
      actions.moveItem('services', services, index, direction);
    })));
    row.appendChild(controlFormat.createCell(createUrlInput(service)));
    row.appendChild(controlFormat.createCell(createRowButtons(service)));
    return row;
  }

  /* ---------- 3. 입력 요소 ---------- */
  // 이름 입력: 바뀐 값만 저장, 비우면 원본 이름으로 되돌림(null)
  function createNameInput(currentName, originalName, onSave, sizeClass) {
    const input = createElement('input', 'input ' + sizeClass);
    input.value = currentName;
    input.maxLength = 60;
    input.placeholder = originalName;
    input.addEventListener('keydown', function (event) { if (event.key === 'Enter') input.blur(); });
    input.addEventListener('change', function () {
      const name = input.value.trim();
      onSave(name && name !== originalName ? name : null);
    });
    return input;
  }

  function createStatusSelect(service) {
    const select = createElement('select', 'select select-xs');
    STATUS_OPTIONS.forEach(function (option) {
      const element = createElement('option', '', option.label);
      element.value = option.value;
      select.appendChild(element);
    });
    select.value = service.status;
    select.addEventListener('change', function () {
      actions.patchService(service.id, { status: select.value === service.original.status ? null : select.value });
    });
    return select;
  }

  // 공개 토글: 인프라는 공개 페이지 대상이 아님 (비활성), 숨긴 프로젝트면 실제 공개 안 됨 안내
  function createPublicToggle(service) {
    const toggle = createToggle(service.is_public, '', function (isChecked) {
      actions.patchService(service.id, { is_public: isChecked === service.original.is_public ? null : isChecked });
    });
    const input = toggle.querySelector('input');
    input.disabled = service.is_infrastructure;
    if (service.is_public && !service.is_listed_publicly) toggle.title = '프로젝트가 숨김이거나 추적 안 함이라 공개되지 않음';
    return toggle;
  }

  // 주소 입력: 비우면 원본 주소로 되돌림(null), 인프라는 외부 점검 없음
  function createUrlInput(service) {
    if (service.is_infrastructure) return createElement('span', 'opacity-50 text-xs', service.has_internal_check ? '내부 점검' : '-');
    const input = createElement('input', 'input input-xs w-56 font-mono');
    input.type = 'url';
    input.value = service.url || '';
    input.placeholder = service.original.url || 'https://';
    input.addEventListener('keydown', function (event) { if (event.key === 'Enter') input.blur(); });
    input.addEventListener('change', function () {
      const url = input.value.trim();
      actions.patchService(service.id, { external_url: url && url !== service.original.url ? url : null });
    });
    return input;
  }

  function createRowButtons(service) {
    const wrapper = createElement('div', 'flex gap-1');
    const infoButton = createIconButton('info', '정보', function () { window.ControlServiceModal.open(service.id); });
    wrapper.appendChild(infoButton);
    if (service.source === 'custom') {
      wrapper.appendChild(createIconButton('trash-2', '삭제', function () {
        if (confirm(service.name + ' 서비스를 삭제할까요? 기록된 점검 결과는 남습니다.')) actions.deleteService(service.id);
      }));
    }
    return wrapper;
  }

  function createMoveButtons(onMove) {
    const wrapper = createElement('div', 'join');
    wrapper.appendChild(createIconButton('chevron-up', '위로', function () { onMove(MOVE_UP); }, 'join-item'));
    wrapper.appendChild(createIconButton('chevron-down', '아래로', function () { onMove(MOVE_DOWN); }, 'join-item'));
    return wrapper;
  }

  function createIconButton(iconName, label, onClick, extraClass) {
    const button = createElement('button', 'btn btn-ghost btn-xs ' + (extraClass || ''));
    button.type = 'button';
    button.title = label;
    button.setAttribute('aria-label', label);
    const icon = createElement('i', 'size-4');
    icon.setAttribute('data-lucide', iconName);
    button.appendChild(icon);
    button.addEventListener('click', onClick);
    return button;
  }

  function createToggle(isChecked, labelText, onChange) {
    const label = createElement('label', 'label cursor-pointer gap-2 text-xs');
    const input = createElement('input', 'toggle toggle-sm toggle-success');
    input.type = 'checkbox';
    input.checked = isChecked;
    input.addEventListener('change', function () { onChange(input.checked); });
    label.appendChild(input);
    if (labelText) label.appendChild(createElement('span', '', labelText));
    return label;
  }

  // 출처 배지: 등록 파일 / 화면 추가 (+ 덮어쓴 칸 수)
  function createSourceBadge(source, overriddenFields) {
    const isCustom = source === 'custom';
    const badge = createElement('span', 'badge badge-xs ' + (isCustom ? 'badge-accent' : 'badge-ghost'), isCustom ? '화면 추가' : '등록 파일');
    if (overriddenFields.length) {
      badge.textContent += ' · 변경 ' + overriddenFields.length;
      badge.title = '덮어쓴 칸: ' + overriddenFields.join(', ');
    }
    return badge;
  }

  /* ---------- 4. 추가 폼 · DNS ---------- */
  function fillProjectSelects() {
    ['control-service-project', 'control-dns-project'].forEach(function (selectId) {
      const select = findElement(selectId);
      const selectedValue = select.value;
      select.replaceChildren();
      manageData.projects.forEach(function (project) {
        const option = createElement('option', '', project.name + ' (' + project.id + ')');
        option.value = project.id;
        select.appendChild(option);
      });
      if (selectedValue) select.value = selectedValue;
    });
  }

  async function submitService(event) {
    event.preventDefault();
    const result = await actions.createService({
      id: findElement('control-service-id').value.trim(), project_id: findElement('control-service-project').value,
      name: findElement('control-service-name').value.trim(), external_url: findElement('control-service-url').value.trim(),
      is_public: findElement('control-service-public').checked,
    });
    if (result.ok) findElement('control-service-form').reset();
  }

  async function submitProject(event) {
    event.preventDefault();
    const result = await actions.createProject({
      id: findElement('control-project-id').value.trim(), name: findElement('control-project-name').value.trim(),
    });
    if (result.ok) findElement('control-project-form').reset();
  }

  async function loadDns() {
    const message = findElement('control-dns-message');
    const list = findElement('control-dns-list');
    message.hidden = false;
    message.textContent = '불러오는 중';
    const loaded = await actions.loadDnsCandidates();
    dnsZoneName = loaded.zone || '';
    message.textContent = loaded.message || (loaded.candidates.length ? '후보 ' + loaded.candidates.length + '개' : '새 도메인이 없습니다');
    list.replaceChildren();
    loaded.candidates.forEach(function (candidate) { list.appendChild(createDnsItem(candidate)); });
    lucide.createIcons();
  }

  function createDnsItem(candidate) {
    const item = createElement('li', 'flex items-center gap-2 py-1.5');
    item.appendChild(createElement('span', 'font-mono text-sm flex-1 break-all', candidate.hostname));
    item.appendChild(createElement('span', 'badge badge-ghost badge-xs', candidate.type + (candidate.is_proxied ? ' · 프록시' : '')));
    const addButton = createElement('button', 'btn btn-outline btn-xs', '추가');
    addButton.type = 'button';
    addButton.addEventListener('click', async function () {
      addButton.disabled = true;
      const result = await actions.importDnsCandidate(candidate, dnsZoneName, findElement('control-dns-project').value);
      if (result.ok) item.remove(); else addButton.disabled = false;
    });
    item.appendChild(addButton);
    return item;
  }

  /* ---------- 5. 시작 ---------- */
  findElement('control-service-form').addEventListener('submit', submitService);
  findElement('control-project-form').addEventListener('submit', submitProject);
  findElement('control-dns-load').addEventListener('click', loadDns);
  document.addEventListener('control-tab-shown', function (event) {
    if (event.detail === 'manage' || event.detail === 'status-page') reload();
  });
  window.ControlManage = { reload: reload };
})();
