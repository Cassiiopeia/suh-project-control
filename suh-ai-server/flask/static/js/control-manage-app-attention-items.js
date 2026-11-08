/* 앱 연동 항목 설정 창: GET 소스 항목 > 줄마다 앱 값(회색) + 덮어쓰기 입력 > 줄 저장 PATCH (빈 값 = null 해제) > 그 줄만 다시 그림
   window.ControlManageAppAttentionItems.open(source) */
(function () {
  const ITEMS_PATH = '/app-attention/items';
  const ITEM_COLUMN_COUNT = 9;
  // 덮어쓰기 칸 > 오류 안내 이름
  const FIELD_LABELS = {
    is_hidden: '표시', label: '이름 (40자 이내)', level_policy: '수준 정책', alert_rule: '알림 규칙', threshold: '기준값', channel_kind: '채널',
  };
  const actions = window.ControlManageActions;
  const controlFormat = window.ControlFormat;
  const attentionFormat = window.AppAttentionFormat;
  const createElement = controlFormat.createElement;

  let currentSource = null;

  function findElement(id) { return document.getElementById(id); }

  function itemsPathOf(source) {
    return window.ControlManageAppAttention.sourcePath(source) + '/items';
  }

  function overridePathOf(source, key) {
    return ITEMS_PATH + '/' + encodeURIComponent(source.project_id) + '/' + encodeURIComponent(source.source_id)
      + '/' + encodeURIComponent(key);
  }

  /* ---------- 1. 열기 · 조회 ---------- */
  async function open(source) {
    currentSource = source;
    findElement('control-attention-items-title').textContent = '항목 설정 · ' + source.project_name + ' / ' + source.source_id;
    const body = findElement('control-attention-items-body');
    body.replaceChildren(controlFormat.createEmptyRow(ITEM_COLUMN_COUNT, '불러오는 중'));
    findElement('control-attention-items-modal').showModal();
    const items = await fetchItems(source);
    body.replaceChildren();
    if (items === null) { body.appendChild(controlFormat.createEmptyRow(ITEM_COLUMN_COUNT, '항목을 불러오지 못했습니다')); return; }
    if (!items.length) { body.appendChild(controlFormat.createEmptyRow(ITEM_COLUMN_COUNT, '아직 받은 항목이 없습니다. 연결 확인으로 응답을 먼저 확인하세요.')); return; }
    items.forEach(function (item) { body.appendChild(createItemRow(item)); });
    lucide.createIcons();
  }

  // 실패 시 null
  async function fetchItems(source) {
    try {
      const result = await actions.sendJson('GET', itemsPathOf(source));
      if (!result.ok) throw new Error('app attention items status ' + result.status);
      return result.data.items;
    } catch (error) {
      console.warn('control app attention items failed:', error);
      return null;
    }
  }

  /* ---------- 2. 줄 ---------- */
  function createItemRow(item) {
    const row = createElement('tr', item.is_missing ? 'opacity-50' : '');
    row.dataset.itemKey = item.key;
    row.appendChild(createKeyCell(item));
    row.appendChild(createAppValueCell(item));
    const controls = createOverrideControls(item);
    ['is_hidden', 'label', 'level_policy', 'alert_rule', 'threshold', 'channel_kind'].forEach(function (field) {
      row.appendChild(controlFormat.createCell(controls[field]));
    });
    row.appendChild(controlFormat.createCell(createSaveControl(item, controls)));
    return row;
  }

  function createKeyCell(item) {
    const cell = createElement('td');
    cell.appendChild(createElement('div', 'font-mono text-xs whitespace-nowrap', item.key));
    const meta = createElement('div', 'flex items-center gap-1 mt-0.5');
    meta.appendChild(createElement('span', 'text-xs opacity-60', item.kind));
    if (item.is_missing) meta.appendChild(createElement('span', 'badge badge-ghost badge-xs', '빠짐'));
    cell.appendChild(meta);
    return cell;
  }

  // 앱이 보낸 원래 값 (회색): 이름 · 수준 · 값
  function createAppValueCell(item) {
    const cell = createElement('td', 'text-xs opacity-60');
    cell.appendChild(createElement('div', 'whitespace-nowrap', item.app.label));
    const appValue = Object.assign({ kind: item.kind }, item.app);
    cell.appendChild(createElement('div', 'whitespace-nowrap',
      attentionFormat.levelBadgeOf(item.app.level).label + ' · ' + attentionFormat.formatItemValue(appValue)));
    return cell;
  }

  // 덮어쓰기 입력 6개 (현재 덮어쓰기 값, 비어 있으면 placeholder·기본 선택지에 유효 값)
  function createOverrideControls(item) {
    const override = item.override;
    const effective = item.effective;
    const shownToggle = createElement('input', 'toggle toggle-sm toggle-success');
    shownToggle.type = 'checkbox';
    shownToggle.checked = !override.is_hidden;
    shownToggle.title = '현황·알림에 표시';
    const labelInput = createElement('input', 'input input-xs');
    labelInput.style.minWidth = '9rem';
    labelInput.maxLength = 40;
    labelInput.value = override.label || '';
    labelInput.placeholder = item.app.label;
    const thresholdInput = createElement('input', 'input input-xs');
    thresholdInput.style.minWidth = '6rem';
    thresholdInput.type = 'number';
    thresholdInput.step = 'any';
    thresholdInput.value = override.threshold === null ? '' : override.threshold;
    thresholdInput.placeholder = override.threshold === null && effective.threshold !== null ? String(effective.threshold) : '';
    return {
      is_hidden: shownToggle,
      label: labelInput,
      level_policy: createOverrideSelect(attentionFormat.LEVEL_POLICY_OPTIONS, override.level_policy, '기본 (앱 값)'),
      alert_rule: createOverrideSelect(attentionFormat.ALERT_RULE_OPTIONS, override.alert_rule,
        override.alert_rule === null ? '기본 · ' + attentionFormat.labelOf(attentionFormat.ALERT_RULE_OPTIONS, effective.rule) : '기본'),
      threshold: thresholdInput,
      channel_kind: createOverrideSelect(attentionFormat.CHANNEL_OPTIONS, override.channel_kind,
        '기본 · ' + attentionFormat.labelOf(attentionFormat.CHANNEL_OPTIONS, 'attention')),
    };
  }

  // 첫 선택지(빈 값) = 덮어쓰기 해제
  function createOverrideSelect(options, currentValue, defaultLabel) {
    const select = createElement('select', 'select select-xs');
    // 표가 좁아도 선택지 문구가 잘리지 않게 (넘치면 가로 스크롤)
    select.style.minWidth = '8.5rem';
    [{ value: '', label: defaultLabel }].concat(options).forEach(function (option) {
      const element = createElement('option', '', option.label);
      element.value = option.value;
      select.appendChild(element);
    });
    select.value = currentValue || '';
    return select;
  }

  function createSaveControl(item, controls) {
    const wrapper = createElement('div', 'flex flex-col items-end gap-1');
    wrapper.style.minWidth = '4rem';
    const button = createElement('button', 'btn btn-outline btn-xs whitespace-nowrap', '저장');
    button.type = 'button';
    const errorText = createElement('span', 'text-xs text-error text-right');
    errorText.style.maxWidth = '8rem';
    errorText.hidden = true;
    button.addEventListener('click', function () { saveRow(item, controls, button, errorText); });
    wrapper.appendChild(button);
    wrapper.appendChild(errorText);
    return wrapper;
  }

  /* ---------- 3. 저장 ---------- */
  // 입력 > PATCH 본문 (표시 켜짐·빈 칸 = null 해제)
  function readOverride(controls) {
    const label = controls.label.value.trim();
    const thresholdText = controls.threshold.value.trim();
    return {
      is_hidden: controls.is_hidden.checked ? null : true,
      label: label || null,
      level_policy: controls.level_policy.value || null,
      alert_rule: controls.alert_rule.value || null,
      threshold: thresholdText === '' ? null : Number(thresholdText),
      channel_kind: controls.channel_kind.value || null,
    };
  }

  async function saveRow(item, controls, button, errorText) {
    Object.keys(controls).forEach(function (field) { controls[field].classList.remove('input-error', 'select-error'); });
    errorText.hidden = true;
    button.disabled = true;
    try {
      const result = await actions.sendJson('PATCH', overridePathOf(currentSource, item.key), readOverride(controls));
      if (!result.ok) { showRowFailure(result, controls, errorText); return; }
      showToast('항목 설정을 저장했습니다', 'success');
      await replaceRow(item.key);
      window.ControlManageAppAttention.notifyChanged();
    } catch (error) {
      console.warn('control app attention override failed:', error);
      errorText.textContent = '요청에 실패했습니다';
      errorText.hidden = false;
    } finally {
      button.disabled = false;
    }
  }

  // 칸 오류: 해당 입력 빨간 테두리 + 칸 이름 안내 / 그 외: 오류 문구
  function showRowFailure(result, controls, errorText) {
    const fields = result.data.fields || [];
    fields.forEach(function (field) {
      const control = controls[field];
      if (control) control.classList.add(control.tagName === 'SELECT' ? 'select-error' : 'input-error');
    });
    errorText.textContent = fields.length
      ? '확인: ' + fields.map(function (field) { return FIELD_LABELS[field] || field; }).join(', ')
      : attentionFormat.describeApiFailure(result);
    errorText.hidden = false;
  }

  // 저장한 줄만 서버 값으로 다시 그림 (다른 줄 입력 중 값 유지)
  async function replaceRow(key) {
    const items = await fetchItems(currentSource);
    const savedItem = items && items.find(function (candidate) { return candidate.key === key; });
    const row = Array.prototype.find.call(findElement('control-attention-items-body').rows,
      function (candidate) { return candidate.dataset.itemKey === key; });
    if (savedItem && row) row.replaceWith(createItemRow(savedItem));
  }

  window.ControlManageAppAttentionItems = { open: open };
})();
