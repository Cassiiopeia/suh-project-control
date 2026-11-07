/* 관제소 탭 3개 (현황 / 서비스 관리 / 상태 페이지): 주소 해시로 탭 기억, 탭을 열면 'control-tab-shown' 이벤트(detail = 탭 이름) */
(function () {
  const DEFAULT_TAB = 'overview';
  const tabButtons = document.querySelectorAll('#control-tabs [data-tab]');
  const tabPanels = document.querySelectorAll('[data-tab-panel]');

  function hasTab(tabName) {
    return Array.prototype.some.call(tabButtons, function (button) { return button.dataset.tab === tabName; });
  }

  function showTab(tabName) {
    const shownTab = hasTab(tabName) ? tabName : DEFAULT_TAB;
    tabButtons.forEach(function (button) { button.classList.toggle('tab-active', button.dataset.tab === shownTab); });
    tabPanels.forEach(function (panel) { panel.hidden = panel.dataset.tabPanel !== shownTab; });
    document.dispatchEvent(new CustomEvent('control-tab-shown', { detail: shownTab }));
  }

  tabButtons.forEach(function (button) {
    button.addEventListener('click', function () {
      history.replaceState(null, '', '#' + button.dataset.tab);
      showTab(button.dataset.tab);
    });
  });
  window.addEventListener('hashchange', function () { showTab(location.hash.slice(1)); });
  showTab(location.hash.slice(1));
})();
