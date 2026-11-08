/* 대시보드 앱 확인할 일 카드. base: /admin → API: ./control/app-attention
   흐름: 진입 시 조회 > 30초 폴링(탭 숨김 시 생략) > 주의 이상 배지 + 프로젝트 줄 최대 5개 (긴급·주의·끊김 많은 순) */
(function () {
  const BOARD_PATH = './control/app-attention';
  const POLL_INTERVAL_MILLISECONDS = 30000;
  const MAX_PROJECT_LINES = 5;
  const attentionFormat = window.AppAttentionFormat;

  function createElement(tagName, className, text) {
    const element = document.createElement(tagName);
    if (className) element.className = className;
    if (text !== undefined) element.textContent = text;
    return element;
  }

  // 프로젝트 1개 > 긴급·주의·열린 항목 수, 끊긴 소스 수
  function summarizeProject(project) {
    const openItems = project.items.filter(function (item) { return item.is_open; });
    const countLevel = function (level) { return openItems.filter(function (item) { return item.level === level; }).length; };
    return {
      name: project.name, openCount: project.open_item_count, criticalCount: countLevel('critical'),
      warningCount: countLevel('warning'),
      failingCount: project.sources.filter(function (source) { return source.is_failing; }).length,
    };
  }

  function compareSeverity(left, right) {
    return (right.criticalCount - left.criticalCount) || (right.warningCount - left.warningCount)
      || (right.failingCount - left.failingCount) || (right.openCount - left.openCount);
  }

  // 배지: 긴급 있으면 빨강, 주의만 있으면 노랑, 없으면 정상 / 소스 없으면 회색
  function renderBadge(board) {
    const badge = document.getElementById('app-attention-badge');
    const summary = board.summary;
    const urgentCount = summary.warning_count + summary.critical_count;
    if (!board.projects.length) { badge.className = 'badge badge-ghost badge-sm'; badge.textContent = '연동 없음'; return; }
    badge.className = 'badge badge-sm ' + (summary.critical_count ? 'badge-error' : (urgentCount ? 'badge-warning' : 'badge-success'));
    badge.textContent = urgentCount ? '주의 이상 ' + urgentCount : '정상';
  }

  function createProjectLine(projectSummary) {
    const line = createElement('li', 'flex items-center gap-2 text-sm');
    line.appendChild(createElement('span', 'font-medium', projectSummary.name));
    const counts = createElement('span', 'flex flex-wrap gap-1 ml-auto');
    [{ level: 'critical', count: projectSummary.criticalCount }, { level: 'warning', count: projectSummary.warningCount }]
      .forEach(function (levelCount) {
        if (!levelCount.count) return;
        const badge = attentionFormat.levelBadgeOf(levelCount.level);
        counts.appendChild(createElement('span', 'badge badge-xs ' + badge.cssClass, badge.label + ' ' + levelCount.count));
      });
    if (projectSummary.failingCount) counts.appendChild(createElement('span', 'badge badge-xs badge-ghost', '연동 끊김'));
    counts.appendChild(createElement('span', 'text-xs opacity-60', '열린 ' + projectSummary.openCount));
    line.appendChild(counts);
    return line;
  }

  function renderProjects(board) {
    const list = document.getElementById('app-attention-projects');
    list.replaceChildren();
    if (!board.projects.length) {
      list.appendChild(createElement('li', 'text-sm opacity-70', '관제소 > 서비스 관리 > 앱 연동에서 소스를 추가하세요'));
      return;
    }
    const summaries = board.projects.map(summarizeProject).sort(compareSeverity);
    summaries.slice(0, MAX_PROJECT_LINES).forEach(function (projectSummary) { list.appendChild(createProjectLine(projectSummary)); });
    if (summaries.length > MAX_PROJECT_LINES) {
      list.appendChild(createElement('li', 'text-xs opacity-60', '외 ' + (summaries.length - MAX_PROJECT_LINES) + '개 프로젝트'));
    }
  }

  async function refreshAppAttention() {
    try {
      const response = await apiFetch(BOARD_PATH);
      if (!response.ok) throw new Error('app attention status ' + response.status);
      const board = await response.json();
      renderBadge(board);
      renderProjects(board);
    } catch (error) {
      const badge = document.getElementById('app-attention-badge');
      badge.className = 'badge badge-ghost badge-sm';
      badge.textContent = '오류';
    }
  }

  document.addEventListener('DOMContentLoaded', function () {
    if (!document.getElementById('app-attention-badge')) return;
    refreshAppAttention();
    setInterval(function () { if (!document.hidden) refreshAppAttention(); }, POLL_INTERVAL_MILLISECONDS);
  });
})();
