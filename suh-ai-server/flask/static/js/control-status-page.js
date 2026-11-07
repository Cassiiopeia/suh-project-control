/* 관제소 상태 페이지 탭: 관리 목록의 page 설정으로 폼 채움 > 저장(PATCH /control/status-page) / 기본값 되돌림(null) */
(function () {
  const actions = window.ControlManageActions;
  const NOTICE_TEXT_MAX_LENGTH = 300;
  const DEFAULT_NOTICE_LEVEL = 'info';

  let isFormDirty = false;  // 입력 중이면 재조회 값으로 덮지 않음

  function findElement(id) { return document.getElementById(id); }

  function fillForm(page) {
    if (isFormDirty) return;
    findElement('control-status-page-title').value = page.title;
    findElement('control-status-page-notice-text').value = page.notice_text;
    findElement('control-status-page-notice-level').value = page.notice_level;
    findElement('control-status-page-preview').href = page.preview_url;
    updateNoticeCount();
  }

  function updateNoticeCount() {
    const length = findElement('control-status-page-notice-text').value.length;
    findElement('control-status-page-notice-count').textContent = length + ' / ' + NOTICE_TEXT_MAX_LENGTH;
  }

  async function save(changes, button) {
    button.disabled = true;
    try {
      const result = await actions.sendJson('PATCH', '/status-page', changes);
      if (!result.ok) { showToast(actions.describeFailure(result), 'error'); return; }
      showToast('상태 페이지 설정을 저장했습니다 (1~2분 안에 반영)', 'success');
      isFormDirty = false;
      if (window.ControlManage) window.ControlManage.reload();
    } catch (error) {
      console.warn('control status page save failed:', error);
      showToast('요청에 실패했습니다', 'error');
    } finally {
      button.disabled = false;
    }
  }

  function submit(event) {
    event.preventDefault();
    save({
      title: findElement('control-status-page-title').value.trim(),
      notice_text: findElement('control-status-page-notice-text').value.trim(),
      notice_level: findElement('control-status-page-notice-level').value,
    }, findElement('control-status-page-submit'));
  }

  function resetToDefault() {
    if (!confirm('사이트 이름을 기본값으로 되돌리고 공지를 지울까요?')) return;
    isFormDirty = false;
    save({ title: null, notice_text: null, notice_level: null }, findElement('control-status-page-reset'));
  }

  findElement('control-status-page-form').addEventListener('submit', submit);
  findElement('control-status-page-form').addEventListener('input', function () { isFormDirty = true; updateNoticeCount(); });
  findElement('control-status-page-reset').addEventListener('click', resetToDefault);
  findElement('control-status-page-notice-level').value = DEFAULT_NOTICE_LEVEL;
  document.addEventListener('control-manage-loaded', function (event) { fillForm(event.detail.page); });
})();
