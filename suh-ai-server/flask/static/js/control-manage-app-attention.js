/* 관제소 서비스 관리 탭 앱 연동: GET /control/app-attention/sources > 소스 표 렌더 / 연결 확인 창 / 삭제
   흐름: 관리 탭 열림 > 조회 > 렌더 > (추가·수정은 폼 창, 항목 설정은 항목 창) > 변경 후 재조회 + 현황 갱신 이벤트 */
(function () {
  const SOURCES_PATH = '/app-attention/sources';
  const SOURCE_COLUMN_COUNT = 5;
  const actions = window.ControlManageActions;
  const controlFormat = window.ControlFormat;
  const attentionFormat = window.AppAttentionFormat;
  const createElement = controlFormat.createElement;

  // 관리 탭 프로젝트 목록 (control-manage.js 'control-manage-loaded' 이벤트로 받음)
  let manageProjects = [];

  function findElement(id) { return document.getElementById(id); }

  function sourcePath(source) {
    return SOURCES_PATH + '/' + encodeURIComponent(source.project_id) + '/' + encodeURIComponent(source.source_id);
  }

  /* ---------- 1. 조회 ---------- */
  async function reload() {
    try {
      const result = await actions.sendJson('GET', SOURCES_PATH);
      if (!result.ok) throw new Error('app attention sources status ' + result.status);
      render(result.data.sources);
    } catch (error) {
      console.warn('control app attention sources failed:', error);
      findElement('control-attention-source-body').replaceChildren(
        controlFormat.createEmptyRow(SOURCE_COLUMN_COUNT, '소스 목록을 불러오지 못했습니다'));
    }
  }

  // 소스 저장·삭제·항목 설정 후: 표 재조회 + 현황 탭 갱신
  function notifyChanged() {
    reload();
    document.dispatchEvent(new CustomEvent('control-app-attention-changed'));
  }

  /* ---------- 2. 소스 표 ---------- */
  function render(sources) {
    findElement('control-attention-source-count').textContent = sources.length;
    const body = findElement('control-attention-source-body');
    body.replaceChildren();
    if (!sources.length) {
      body.appendChild(controlFormat.createEmptyRow(SOURCE_COLUMN_COUNT, '연동한 앱이 없습니다. 추가 버튼으로 첫 소스를 등록하세요.'));
      return;
    }
    sources.forEach(function (source) { body.appendChild(createSourceRow(source)); });
    lucide.createIcons();
  }

  function createSourceRow(source) {
    const row = createElement('tr', source.is_enabled ? '' : 'opacity-50');
    const nameCell = createElement('td');
    nameCell.appendChild(createElement('div', 'font-semibold', source.project_name));
    const idLine = createElement('div', 'flex items-center gap-1');
    idLine.appendChild(createElement('span', 'font-mono text-xs opacity-60 whitespace-nowrap', source.project_id + ' / ' + source.source_id));
    if (!source.is_enabled) idLine.appendChild(createElement('span', 'badge badge-ghost badge-xs', '꺼짐'));
    nameCell.appendChild(idLine);
    row.appendChild(nameCell);

    // 수집: 방식 · 주기 · 끊김 판정 / 주소
    const collectCell = createElement('td', 'text-xs');
    collectCell.style.minWidth = '14rem';
    collectCell.appendChild(createElement('div', '', attentionFormat.describeMode(source.mode) + ' · ' + source.interval_seconds
      + '초마다 · 끊김 ' + source.stale_after_seconds + '초'));
    collectCell.appendChild(createElement('div', 'font-mono opacity-60 break-all', source.url || '주소 없음 (push만)'));
    row.appendChild(collectCell);
    row.appendChild(controlFormat.createCell(createTokenList(source)));
    row.appendChild(controlFormat.createCell(createLastResult(source)));
    row.appendChild(controlFormat.createCell(createRowButtons(source)));
    return row;
  }

  // 토큰: 방식에 필요한 환경변수 이름 + 설정 여부 (값은 표시하지 않음)
  function createTokenList(source) {
    const list = createElement('div', 'space-y-1');
    [[source.pull_token_env_name, source.is_pull_token_configured], [source.push_token_env_name, source.is_push_token_configured]]
      .filter(function (token) { return token[0]; })
      .forEach(function (token) {
        const line = createElement('div', 'flex items-center gap-1 whitespace-nowrap');
        line.appendChild(createElement('span', 'badge badge-xs ' + (token[1] ? 'badge-success' : 'badge-warning'), token[1] ? '설정됨' : '없음'));
        line.appendChild(createElement('span', 'font-mono text-xs opacity-70', token[0]));
        list.appendChild(line);
      });
    return list;
  }

  // 마지막 결과: 배지(성공/끊김/실패) + 사유 + 시도 시각 + 항목 수
  function createLastResult(source) {
    const wrapper = createElement('div', 'text-xs space-y-0.5');
    const state = source.state;
    if (!state || !state.last_result) {
      wrapper.appendChild(createElement('span', 'badge badge-ghost badge-sm', '기록 없음'));
      return wrapper;
    }
    const isSuccess = attentionFormat.isSuccessResult(state.last_result);
    const badgeClass = source.is_failing ? 'badge-error' : (isSuccess ? 'badge-success' : 'badge-warning');
    const badgeLine = createElement('div', 'flex flex-wrap items-center gap-1');
    badgeLine.appendChild(createElement('span', 'badge badge-sm ' + badgeClass,
      source.is_failing ? '연동 끊김' : attentionFormat.describeResult(state.last_result)));
    const reason = attentionFormat.describeError(state.last_error);
    if (reason) badgeLine.appendChild(createElement('span', 'opacity-80', reason));
    wrapper.appendChild(badgeLine);
    wrapper.appendChild(createElement('div', 'opacity-60 whitespace-nowrap', '시도 ' + controlFormat.formatElapsed(state.last_attempt_at)
      + ' · 성공 ' + (state.last_success_at ? controlFormat.formatElapsed(state.last_success_at) : '없음')));
    wrapper.appendChild(createElement('div', 'opacity-60', '항목 ' + source.item_count + ' · 열린 ' + source.open_item_count));
    return wrapper;
  }

  function createRowButtons(source) {
    // 버튼 4개를 2줄로 (표가 좁아져도 아이콘·문구가 눌리지 않게 폭 고정)
    const wrapper = createElement('div', 'flex flex-wrap gap-1 justify-end');
    wrapper.style.width = '12rem';
    wrapper.appendChild(createTextButton('plug-zap', '연결 확인', function (button) { testSource(source, button); }));
    wrapper.appendChild(createTextButton('list-checks', '항목 설정', function () { window.ControlManageAppAttentionItems.open(source); }));
    wrapper.appendChild(createTextButton('pencil', '수정', function () {
      window.ControlManageAppAttentionForm.open(manageProjects, source);
    }));
    wrapper.appendChild(createTextButton('trash-2', '삭제', function () { deleteSource(source); }));
    return wrapper;
  }

  function createTextButton(iconName, label, onClick) {
    const button = createElement('button', 'btn btn-ghost btn-xs whitespace-nowrap');
    button.type = 'button';
    const icon = createElement('i', 'size-3.5 shrink-0');
    icon.setAttribute('data-lucide', iconName);
    button.appendChild(icon);
    button.appendChild(document.createTextNode(label));
    button.addEventListener('click', function () { onClick(button); });
    return button;
  }

  /* ---------- 3. 삭제 ---------- */
  async function deleteSource(source) {
    if (!confirm(source.project_name + ' / ' + source.source_id + ' 소스를 삭제할까요? 항목·이력·항목 설정도 함께 지워집니다.')) return;
    const result = await actions.sendJson('DELETE', sourcePath(source));
    if (!result.ok) { showToast(attentionFormat.describeApiFailure(result), 'error'); return; }
    showToast('소스를 삭제했습니다', 'success');
    notifyChanged();
  }

  /* ---------- 4. 연결 확인 ---------- */
  async function testSource(source, button) {
    const modal = findElement('control-attention-test-modal');
    const body = findElement('control-attention-test-body');
    findElement('control-attention-test-title').textContent = '연결 확인 · ' + source.project_name + ' / ' + source.source_id;
    body.replaceChildren(createElement('div', 'opacity-60', '확인 중'));
    modal.showModal();
    button.disabled = true;
    try {
      const result = await actions.sendJson('POST', sourcePath(source) + '/test');
      body.replaceChildren();
      if (!result.ok) { body.appendChild(createElement('div', 'text-error', attentionFormat.describeApiFailure(result))); return; }
      renderTestResult(body, result.data);
    } catch (error) {
      console.warn('control app attention test failed:', error);
      body.replaceChildren(createElement('div', 'text-error', '요청에 실패했습니다'));
    } finally {
      button.disabled = false;
    }
  }

  // 미리보기: 결과·사유 > 최상위 오류 > 버린 항목 > 받은 항목 표
  function renderTestResult(body, preview) {
    const isSuccess = preview.result === 'ok';
    const resultLine = createElement('div', 'flex flex-wrap items-center gap-2');
    resultLine.appendChild(createElement('span', 'badge ' + (isSuccess ? 'badge-success' : 'badge-error'), attentionFormat.describeResult(preview.result)));
    if (preview.error_label) resultLine.appendChild(createElement('span', 'font-mono text-xs', attentionFormat.describeError(preview.error_label)));
    resultLine.appendChild(createElement('span', 'text-xs opacity-60 ml-auto', '받은 항목 ' + preview.items.length));
    body.appendChild(resultLine);
    if (preview.errors.length) body.appendChild(createMessageList('규격 오류', preview.errors.map(attentionFormat.describeError), 'text-error'));
    if (preview.dropped_items.length) {
      body.appendChild(createMessageList('버린 항목 ' + preview.dropped_items.length, preview.dropped_items.map(function (dropped) {
        return dropped.key + ' : ' + dropped.reason;
      }), 'text-warning'));
    }
    if (preview.items.length) body.appendChild(createPreviewTable(preview.items));
  }

  function createMessageList(title, messages, colorClass) {
    const block = createElement('div');
    block.appendChild(createElement('div', 'text-xs font-semibold mb-1 ' + colorClass, title));
    const list = createElement('ul', 'text-xs font-mono space-y-0.5');
    messages.forEach(function (message) { list.appendChild(createElement('li', '', message)); });
    block.appendChild(list);
    return block;
  }

  function createPreviewTable(items) {
    const wrapper = createElement('div', 'overflow-x-auto');
    const table = createElement('table', 'table table-sm');
    const headRow = createElement('tr');
    ['key', '이름', '종류', '수준', '값'].forEach(function (label) { headRow.appendChild(createElement('th', '', label)); });
    table.appendChild(createElement('thead')).appendChild(headRow);
    const tableBody = createElement('tbody');
    items.forEach(function (item) {
      const row = createElement('tr');
      const badge = attentionFormat.levelBadgeOf(item.level);
      row.appendChild(controlFormat.createCell(item.key, 'font-mono text-xs'));
      row.appendChild(controlFormat.createCell(item.label));
      row.appendChild(controlFormat.createCell(item.kind, 'text-xs opacity-70'));
      row.appendChild(controlFormat.createCell(createElement('span', 'badge badge-sm ' + badge.cssClass, badge.label)));
      row.appendChild(controlFormat.createCell(item.summary || '-', 'font-mono text-xs'));
      tableBody.appendChild(row);
    });
    table.appendChild(tableBody);
    wrapper.appendChild(table);
    return wrapper;
  }

  /* ---------- 5. 시작 ---------- */
  findElement('control-attention-source-add').addEventListener('click', function () {
    window.ControlManageAppAttentionForm.open(manageProjects, null);
  });
  document.addEventListener('control-manage-loaded', function (event) { manageProjects = event.detail.projects; });
  document.addEventListener('control-tab-shown', function (event) { if (event.detail === 'manage') reload(); });
  window.ControlManageAppAttention = { reload: reload, notifyChanged: notifyChanged, sourcePath: sourcePath };
})();
