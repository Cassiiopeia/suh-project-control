/* 관제소 현황 탭 앱 확인할 일. API: ../control/app-attention
   흐름: 진입 시 조회 > 30초 폴링(탭 숨김 시 생략) > 프로젝트별 카드 (연동 끊김 줄 > 열린 항목 그룹별 > 접힌 정상 n개) */
(function () {
  const BOARD_PATH = '../control/app-attention';
  // 현황 탭 overview 폴링과 같은 주기
  const POLL_INTERVAL_MILLISECONDS = 30000;
  // 링크로 여는 주소 형식 (서버 검증과 별개로 javascript: 등 차단)
  const WEB_URL_PATTERN = /^https?:\/\//;
  const controlFormat = window.ControlFormat;
  const attentionFormat = window.AppAttentionFormat;
  const createElement = controlFormat.createElement;

  let isLoadingBoard = false;
  // 펼친 "정상 n개" 프로젝트 id (폴링으로 다시 그려도 유지)
  const expandedProjectIds = new Set();

  function findElement(id) { return document.getElementById(id); }

  /* ---------- 1. 조회 · 폴링 ---------- */
  async function loadBoard() {
    if (document.hidden || isLoadingBoard) return;
    isLoadingBoard = true;
    try {
      const response = await apiFetch(BOARD_PATH);
      if (!response.ok) throw new Error('app attention status ' + response.status);
      render(await response.json());
    } catch (error) {
      console.warn('control app attention failed:', error);
      findElement('control-app-attention-projects').replaceChildren(
        createElement('div', 'text-error text-sm', '앱 확인할 일을 불러오지 못했습니다'));
    } finally {
      isLoadingBoard = false;
    }
  }

  /* ---------- 2. 렌더 ---------- */
  function render(board) {
    renderSummary(board.summary);
    const container = findElement('control-app-attention-projects');
    container.replaceChildren();
    if (!board.projects.length) { container.appendChild(createEmptyGuide()); return; }
    board.projects.forEach(function (project) { container.appendChild(createProjectCard(project)); });
    lucide.createIcons();
  }

  // 제목 배지: 긴급 있으면 빨강, 주의 있으면 노랑, 그 외 회색 / 연동 끊김 수
  function renderSummary(summary) {
    const countBadge = findElement('control-app-attention-count');
    const colorClass = summary.critical_count ? 'badge-error' : (summary.warning_count ? 'badge-warning' : 'badge-ghost');
    countBadge.className = 'badge badge-sm ' + colorClass;
    countBadge.textContent = '열린 ' + summary.open_item_count;
    const failingBadge = findElement('control-app-attention-failing');
    failingBadge.hidden = !summary.failing_source_count;
    failingBadge.className = 'badge badge-sm badge-ghost';
    failingBadge.textContent = '연동 끊김 ' + summary.failing_source_count;
  }

  function createEmptyGuide() {
    const guide = createElement('div', 'text-sm opacity-70 lg:col-span-2');
    guide.appendChild(document.createTextNode('아직 연동한 앱이 없습니다. '));
    const link = createElement('a', 'link link-primary', '서비스 관리 탭');
    link.href = '#manage';
    guide.appendChild(link);
    guide.appendChild(document.createTextNode('의 "앱 연동"에서 소스를 추가하세요.'));
    return guide;
  }

  function createProjectCard(project) {
    const card = createElement('div', 'rounded-box border border-base-300 p-3 space-y-2');
    const openItems = project.items.filter(function (item) { return item.is_open; });
    const closedItems = project.items.filter(function (item) { return !item.is_open; });
    const failingSources = project.sources.filter(function (source) { return source.is_failing; });
    card.appendChild(createProjectHeader(project, openItems));
    failingSources.forEach(function (source) { card.appendChild(createFailingRow(source)); });
    groupItems(openItems).forEach(function (group) { card.appendChild(createGroupBlock(group)); });
    if (!openItems.length && !failingSources.length) card.appendChild(createQuietMessage(project));
    if (closedItems.length) card.appendChild(createClosedItems(project.id, closedItems));
    return card;
  }

  // 머리: 이름 + 긴급·주의 수 (수준별 배지는 해당 항목 있을 때만)
  function createProjectHeader(project, openItems) {
    const header = createElement('div', 'flex flex-wrap items-center gap-2');
    header.appendChild(createElement('h3', 'font-semibold', project.name));
    ['critical', 'warning'].forEach(function (level) {
      const count = openItems.filter(function (item) { return item.level === level; }).length;
      if (!count) return;
      const badge = attentionFormat.levelBadgeOf(level);
      header.appendChild(createElement('span', 'badge badge-xs ' + badge.cssClass, badge.label + ' ' + count));
    });
    header.appendChild(createElement('span', 'text-xs opacity-60 ml-auto', '열린 ' + project.open_item_count));
    return header;
  }

  // 연동 끊김 줄: 소스 · 사유 · 마지막 성공 시각
  function createFailingRow(source) {
    const row = createElement('div', 'flex items-start gap-2 rounded-box bg-base-200 px-2 py-1.5 text-xs opacity-80');
    const icon = createElement('i', 'size-4 shrink-0');
    icon.setAttribute('data-lucide', 'unplug');
    row.appendChild(icon);
    const reason = attentionFormat.describeError(source.last_error)
      || (attentionFormat.isSuccessResult(source.last_result) ? '응답이 오래 없음' : attentionFormat.describeResult(source.last_result));
    const lastSuccess = source.last_success_at
      ? controlFormat.formatDateTime(source.last_success_at) + ' (' + controlFormat.formatElapsed(source.last_success_at) + ')' : '없음';
    row.appendChild(createElement('span', '', '연동 끊김 · ' + source.source_id + ' · ' + reason + ' · 마지막 성공 ' + lastSuccess));
    return row;
  }

  // 열린 항목·끊김 없음: 한 번도 수집 안 했으면 대기, 아니면 정상
  function createQuietMessage(project) {
    const hasAnyResult = project.sources.some(function (source) { return source.last_result; });
    return hasAnyResult
      ? createElement('div', 'text-sm text-success', '확인할 일이 없습니다')
      : createElement('div', 'text-sm opacity-60', '아직 수집 전입니다 (저장 후 다음 점검에 반영)');
  }

  // 그룹 순서는 처음 나온 순서 (API가 열린 항목·수준 순으로 정렬해 줌)
  function groupItems(items) {
    const groups = [];
    items.forEach(function (item) {
      const groupName = item.group || '';
      let group = groups.find(function (candidate) { return candidate.name === groupName; });
      if (!group) { group = { name: groupName, items: [] }; groups.push(group); }
      group.items.push(item);
    });
    return groups;
  }

  function createGroupBlock(group) {
    const block = createElement('div');
    if (group.name) block.appendChild(createElement('div', 'text-xs font-semibold opacity-60 mt-1', group.name));
    const list = createElement('div', 'divide-y divide-base-300');
    group.items.forEach(function (item) { list.appendChild(createItemRow(item)); });
    block.appendChild(list);
    return block;
  }

  // 항목 줄: 수준 배지 · 이름(앱 관리자 링크) · 값 / 상세 · 갱신 시각
  function createItemRow(item) {
    const row = createElement('div', 'py-1.5');
    const mainLine = createElement('div', 'flex items-center gap-2 text-sm');
    const badge = attentionFormat.levelBadgeOf(item.level);
    mainLine.appendChild(createElement('span', 'badge badge-sm shrink-0 ' + badge.cssClass, badge.label));
    mainLine.appendChild(createItemLabel(item));
    mainLine.appendChild(createElement('span', 'font-mono text-xs ml-auto whitespace-nowrap', attentionFormat.formatItemValue(item)));
    row.appendChild(mainLine);
    const subText = [item.detail, item.updated_at ? '갱신 ' + controlFormat.formatElapsed(item.updated_at) : null]
      .filter(Boolean).join(' · ');
    if (subText) row.appendChild(createElement('div', 'text-xs opacity-60 mt-0.5', subText));
    return row;
  }

  // 앱 관리자 주소(http·https만) 있으면 새 탭 링크
  function createItemLabel(item) {
    if (!item.admin_url || !WEB_URL_PATTERN.test(item.admin_url)) {
      const label = createElement('span', 'font-medium', item.label);
      if (item.description) label.title = item.description;
      return label;
    }
    const link = createElement('a', 'link link-hover font-medium inline-flex items-center gap-1', item.label);
    link.href = item.admin_url;
    link.target = '_blank';
    link.rel = 'noopener noreferrer';
    if (item.description) link.title = item.description;
    const icon = createElement('i', 'size-3 opacity-60');
    icon.setAttribute('data-lucide', 'external-link');
    link.appendChild(icon);
    return link;
  }

  // 0건·ok 항목: 접힌 "정상 n개" (펼침 상태 유지)
  function createClosedItems(projectId, items) {
    const details = createElement('details', 'text-sm');
    details.open = expandedProjectIds.has(projectId);
    details.addEventListener('toggle', function () {
      if (details.open) expandedProjectIds.add(projectId); else expandedProjectIds.delete(projectId);
    });
    details.appendChild(createElement('summary', 'cursor-pointer text-xs opacity-60', '정상 ' + items.length + '개'));
    const list = createElement('div', 'divide-y divide-base-300 opacity-70');
    items.forEach(function (item) { list.appendChild(createItemRow(item)); });
    details.appendChild(list);
    return details;
  }

  /* ---------- 3. 시작 ---------- */
  loadBoard();
  setInterval(loadBoard, POLL_INTERVAL_MILLISECONDS);
  document.addEventListener('visibilitychange', function () { if (!document.hidden) loadBoard(); });
  // 관리 탭에서 소스·항목 설정을 바꾸면 바로 갱신
  document.addEventListener('control-app-attention-changed', loadBoard);
  window.ControlAppAttention = { reload: loadBoard };
})();
