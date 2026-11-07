/* 관제소 프로젝트 카드 머리의 디스코드 초대 링크: 없으면 "초대 링크" 버튼(발급), 있으면 주소·복사·다시 만들기
   POST /control/projects/{id}/invite (?regenerate=1) > 성공 시 ControlManage.reload() / window.ControlManageInvite 로 노출 */
(function () {
  const actions = window.ControlManageActions;
  const createElement = window.ControlFormat.createElement;
  const REGENERATE_CONFIRM_TEXT = '초대 링크를 다시 만들까요? 기존 링크는 더 이상 쓸 수 없습니다.';

  // 발급 1건: 실패 안내 > 성공 문구 > 목록 재조회
  async function requestInvite(projectId, shouldRegenerate) {
    const path = '/projects/' + encodeURIComponent(projectId) + '/invite' + (shouldRegenerate ? '?regenerate=1' : '');
    try {
      const result = await actions.sendJson('POST', path);
      if (!result.ok) { showToast(actions.describeFailure(result), 'error'); return; }
      showToast(shouldRegenerate ? '초대 링크를 다시 만들었습니다' : '초대 링크를 만들었습니다', 'success');
      if (window.ControlManage) window.ControlManage.reload();
    } catch (error) {
      console.warn('control invite failed:', error);
      showToast('요청에 실패했습니다', 'error');
    }
  }

  // 클립보드 복사 (clipboard API 없으면 입력칸 선택 > execCommand)
  async function copyInviteUrl(input) {
    try {
      if (navigator.clipboard && window.isSecureContext) {
        await navigator.clipboard.writeText(input.value);
      } else {
        input.select();
        document.execCommand('copy');
      }
      showToast('초대 링크를 복사했습니다', 'success');
    } catch (error) {
      console.warn('control invite copy failed:', error);
      showToast('복사하지 못했습니다. 직접 선택해 복사하세요', 'error');
    }
  }

  function createButton(iconName, labelText, extraClass, onClick) {
    const button = createElement('button', 'btn btn-xs ' + extraClass);
    button.type = 'button';
    button.title = labelText;
    const icon = createElement('i', 'size-4');
    icon.setAttribute('data-lucide', iconName);
    button.appendChild(icon);
    button.appendChild(createElement('span', '', labelText));
    button.addEventListener('click', onClick);
    return button;
  }

  // 초대 없음: 발급 버튼 1개 (누르는 동안 비활성)
  function createIssueButton(project) {
    const button = createButton('link', '초대 링크', 'btn-outline', async function () {
      button.disabled = true;
      await requestInvite(project.id, false);
      button.disabled = false;
    });
    return button;
  }

  // 초대 있음: 주소 입력칸(읽기 전용) + 복사 + 다시 만들기(확인 창)
  function createInviteGroup(project) {
    const group = createElement('div', 'join');
    const input = createElement('input', 'input input-xs join-item font-mono w-48');
    input.readOnly = true;
    input.value = project.invite_url;
    input.setAttribute('aria-label', project.name + ' 초대 링크');
    input.addEventListener('focus', function () { input.select(); });
    group.appendChild(input);
    group.appendChild(createButton('copy', '복사', 'join-item', function () { copyInviteUrl(input); }));
    group.appendChild(createButton('refresh-cw', '다시 만들기', 'join-item btn-ghost', function () {
      if (confirm(REGENERATE_CONFIRM_TEXT)) requestInvite(project.id, true);
    }));
    return group;
  }

  function createInviteControl(project) {
    return project.invite_url ? createInviteGroup(project) : createIssueButton(project);
  }

  window.ControlManageInvite = { createInviteControl: createInviteControl };
})();
