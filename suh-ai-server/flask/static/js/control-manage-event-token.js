/* 관제소 프로젝트 카드의 "이벤트 토큰" 영역: 상태 줄(관리 방식·현재 발급 시각·이전 만료 시각) + 발급·교체·폐기 버튼
   POST·DELETE /control/projects/{id}/event-token > 발급 원문은 결과 창에 1번만 표시(닫으면 비움) > ControlManage.reload()
   window.ControlManageEventToken 로 노출, 비밀값 설정 여부는 GET /control/manage 의 is_token_secret_configured */
(function () {
  const actions = window.ControlManageActions;
  const controlFormat = window.ControlFormat;
  const createElement = controlFormat.createElement;
  const MANAGED_BY_ADMIN_LABEL = '관리 화면';
  const MANAGED_BY_ENV_LABEL = '환경변수';
  const ROTATE_CONFIRM_TEXT = '토큰을 교체할까요? 지금 토큰은 7일 뒤 만료됩니다. 새 토큰으로 앱을 배포하세요.';
  const FIRST_ISSUE_ENV_CONFIRM_TEXT = '토큰을 발급할까요? 발급하면 이 프로젝트의 환경변수 토큰은 더 이상 쓸 수 없습니다.';
  const REVOKE_CONFIRM_TEXT = '토큰을 폐기할까요? 현재·이전 토큰 모두 바로 거부되고 환경변수 토큰으로 돌아가지 않습니다.';
  // 비밀값 없음 안내 = 409 secret_not_configured 문구 (ControlManageActions 오류 문구 원본 사용)
  const SECRET_MISSING_TEXT = actions.describeFailure({ status: 409, data: { error: 'secret_not_configured' } });

  function findElement(id) { return document.getElementById(id); }

  // 결과 창 닫힘 > 토큰 값 비움 (다시 열어도 볼 수 없게)
  function clearTokenModalOnClose() {
    const modal = findElement('control-event-token-modal');
    if (!modal || modal.dataset.isCloseBound) return;
    modal.dataset.isCloseBound = 'true';
    modal.addEventListener('close', function () {
      findElement('control-event-token-value').value = '';
      findElement('control-event-token-previous').textContent = '';
    });
    findElement('control-event-token-copy').addEventListener('click', copyTokenValue);
  }

  // 클립보드 복사 (clipboard API 없으면 입력칸 선택 > execCommand)
  async function copyTokenValue() {
    const input = findElement('control-event-token-value');
    try {
      if (navigator.clipboard && window.isSecureContext) {
        await navigator.clipboard.writeText(input.value);
      } else {
        input.select();
        document.execCommand('copy');
      }
      showToast('토큰을 복사했습니다', 'success');
    } catch (error) {
      console.warn('control event token copy failed');  // 토큰 값은 콘솔에 남기지 않음
      showToast('복사하지 못했습니다. 직접 선택해 복사하세요', 'error');
    }
  }

  // 결과 창: 원문 + 이전 토큰 만료 시각 (교체일 때만)
  function openTokenModal(project, issued) {
    clearTokenModalOnClose();
    findElement('control-event-token-modal-title').textContent = project.name + ' 이벤트 토큰';
    findElement('control-event-token-value').value = issued.token;
    findElement('control-event-token-previous').textContent = issued.previous_expires_at
      ? '이전 토큰 만료: ' + controlFormat.formatDateTime(issued.previous_expires_at) + ' (그 전에 새 토큰으로 배포)' : '';
    findElement('control-event-token-modal').showModal();
  }

  function eventTokenPath(projectId) {
    return '/projects/' + encodeURIComponent(projectId) + '/event-token';
  }

  // 요청 1건: 실패 안내 > 성공 처리 > 목록 재조회
  async function requestEventToken(method, project, successMessage) {
    try {
      const result = await actions.sendJson(method, eventTokenPath(project.id));
      if (!result.ok) { showToast(actions.describeFailure(result), 'error'); return; }
      if (method === 'POST') openTokenModal(project, result.data);
      showToast(successMessage, 'success');
      if (window.ControlManage) window.ControlManage.reload();
    } catch (error) {
      console.warn('control event token request failed:', error && error.name);
      showToast('요청에 실패했습니다', 'error');
    }
  }

  /* ---------- 1. 상태 줄 ---------- */
  function describeManagedBy(tokenStatus) {
    if (tokenStatus.is_db_managed) return MANAGED_BY_ADMIN_LABEL;
    return MANAGED_BY_ENV_LABEL + (tokenStatus.is_env_configured ? '' : ' (미설정)');
  }

  function createStatusLine(tokenStatus) {
    const line = createElement('div', 'flex flex-wrap gap-x-4 gap-y-1 text-xs');
    line.appendChild(createElement('span', '', '관리 방식: ' + describeManagedBy(tokenStatus)));
    line.appendChild(createElement('span', '', '현재 토큰 발급: ' +
      (tokenStatus.has_current ? controlFormat.formatDateTime(tokenStatus.current_created_at) : '없음')));
    line.appendChild(createElement('span', '', '이전 토큰 만료: ' +
      (tokenStatus.has_previous ? controlFormat.formatDateTime(tokenStatus.previous_expires_at) : '없음')));
    return line;
  }

  /* ---------- 2. 버튼 ---------- */
  function createButton(iconName, labelText, extraClass, isSecretConfigured, onClick) {
    const button = createElement('button', 'btn btn-xs ' + extraClass);
    button.type = 'button';
    button.disabled = !isSecretConfigured;
    const icon = createElement('i', 'size-4');
    icon.setAttribute('data-lucide', iconName);
    button.appendChild(icon);
    button.appendChild(createElement('span', '', labelText));
    button.addEventListener('click', async function () {
      button.disabled = true;
      await onClick();
      button.disabled = false;
    });
    return button;
  }

  // 발급(처음)·교체(현재 있음)·폐기(현재 또는 이전 있음), 확인 창 거친 뒤 요청
  function createButtonGroup(project, isSecretConfigured) {
    const tokenStatus = project.event_token;
    const group = createElement('div', 'flex flex-wrap items-center gap-2 mt-2');
    if (tokenStatus.has_current) {
      group.appendChild(createButton('refresh-cw', '토큰 교체', 'btn-outline', isSecretConfigured, async function () {
        if (confirm(ROTATE_CONFIRM_TEXT)) await requestEventToken('POST', project, '토큰을 교체했습니다');
      }));
    } else {
      group.appendChild(createButton('key-round', '토큰 발급', 'btn-outline', isSecretConfigured, async function () {
        // 환경변수 토큰을 쓰던 프로젝트는 발급 순간 환경변수 토큰이 막힘 > 확인
        const isEnvTokenInUse = !tokenStatus.is_db_managed && tokenStatus.is_env_configured;
        if (isEnvTokenInUse && !confirm(FIRST_ISSUE_ENV_CONFIRM_TEXT)) return;
        await requestEventToken('POST', project, '토큰을 발급했습니다');
      }));
    }
    if (tokenStatus.has_current || tokenStatus.has_previous) {
      group.appendChild(createButton('trash-2', '토큰 폐기', 'btn-ghost text-error', isSecretConfigured, async function () {
        if (confirm(REVOKE_CONFIRM_TEXT)) await requestEventToken('DELETE', project, '토큰을 폐기했습니다');
      }));
    }
    if (!isSecretConfigured) group.appendChild(createElement('span', 'text-xs text-warning', SECRET_MISSING_TEXT));
    return group;
  }

  /* ---------- 3. 영역 ---------- */
  function createEventTokenSection(project, isSecretConfigured) {
    const section = createElement('div', 'mt-2 text-sm');
    section.appendChild(createElement('div', 'text-xs opacity-70', '이벤트 토큰 · 앱이 이벤트를 보낼 때 X-Control-Token 헤더에 사용'));
    section.appendChild(createStatusLine(project.event_token));
    section.appendChild(createButtonGroup(project, isSecretConfigured));
    return section;
  }

  window.ControlManageEventToken = { createEventTokenSection: createEventTokenSection };
})();
