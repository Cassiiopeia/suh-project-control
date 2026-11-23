/* gbrain 팀 브레인 카드 (#210): 목록·상태 > 만들기(결과 창 1회) > 재시작 > 로그
   API: ../gbrain/teams (GET 목록, POST 만들기), ../gbrain/teams/{project}/control/{action}, ../gbrain/teams/{project}/logs
   목록을 읽으면 'gbrain-teams-loaded' 이벤트로 토큰 카드의 브레인 선택지를 채움
   새 쓰기 계정 비번은 결과 창 입력칸에만 두고 닫으면 비움 */
(function () {
  const { getElement, readResponseBody, describeFailure } = window.gbrainPage;
  const API = '../gbrain/teams';
  const LIST_REFRESH_MILLISECONDS = 15000;
  const LOG_LINES = 200;

  // 서비스 상태 코드 > 표시 문구 (gbrain.js 와 같은 값)
  const SERVICE_STATE_LABELS = {
    running: '구동 중', stopped: '정지됨', start_pending: '시작 중', stop_pending: '중지 중',
    not_installed: '미설치', unknown: '확인 불가',
  };
  // 만들기 단계 > 표시 이름, 결과 값 > 문구
  const STEP_LABELS = {
    database: 'DB', writer_role: '쓰기 계정', prepare: '브레인 준비', admin_token: '관리자 토큰', config: 'gbrain 설정',
    service: '서버(서비스)', nginx: '공개 주소', monitoring: '관제소 감시',
  };
  const STEP_RESULT_LABELS = {
    created: '새로 만들었어요', kept: '있던 것을 그대로 써요', prepared: '준비했어요', written: '설정을 쓰고 스키마를 맞췄어요',
    initialized: '새 브레인으로 초기화했어요', installed: '설치·기동하고 헬스를 확인했어요', published: '공개 경로를 열었어요',
    included: '팀 브레인 전체 감시에 포함됐어요',
  };

  /* ---------- 1. 목록 ---------- */
  async function loadTeams() {
    const tableBody = getElement('team-table-body');
    try {
      const response = await apiFetch(API + '?t=' + Date.now());
      const responseBody = await readResponseBody(response);
      if (!response.ok) throw new Error(describeFailure(responseBody, '팀 브레인 목록을 불러오지 못했어요'));
      const brains = responseBody.brains || [];
      renderTeams(brains);
      document.dispatchEvent(new CustomEvent('gbrain-teams-loaded', { detail: { brains: brains } }));
    } catch (error) {
      tableBody.innerHTML = '<tr><td colspan="6" class="text-center text-error py-6">' + escapeHtml(error.message) + '</td></tr>';
    }
  }

  function renderTeams(brains) {
    const tableBody = getElement('team-table-body');
    if (!brains.length) {
      tableBody.innerHTML = '<tr><td colspan="6" class="text-center opacity-50 py-6">아직 팀 브레인이 없어요. "팀 브레인 만들기"로 시작해 보세요.</td></tr>';
      return;
    }
    tableBody.innerHTML = brains.map(renderTeamRow).join('');
    tableBody.querySelectorAll('[data-team-restart]').forEach(function (button) {
      button.addEventListener('click', function () { restartTeam(button.dataset.teamRestart, button); });
    });
    tableBody.querySelectorAll('[data-team-logs]').forEach(function (button) {
      button.addEventListener('click', function () { openLogs(button.dataset.teamLogs); });
    });
    if (window.lucide) lucide.createIcons();
  }

  function renderTeamRow(brain) {
    const stateLabel = SERVICE_STATE_LABELS[brain.service_state] || brain.service_state || '-';
    const serviceBadge = brain.service_running
      ? '<span class="badge badge-success badge-sm whitespace-nowrap">' + escapeHtml(stateLabel) + '</span>'
      : '<span class="badge badge-error badge-sm whitespace-nowrap">' + escapeHtml(stateLabel) + '</span>';
    const healthBadge = brain.is_healthy
      ? '<span class="badge badge-success badge-sm whitespace-nowrap">정상</span>'
      : '<span class="badge ' + (brain.service_running ? 'badge-warning' : 'badge-ghost') + ' badge-sm whitespace-nowrap">응답 없음</span>';
    const project = escapeHtml(brain.project);
    return '<tr>' +
      '<td><div class="font-mono text-xs font-semibold">' + project + '</div>' +
      '<div class="font-mono text-[10px] opacity-50">' + escapeHtml(brain.service_name) + '</div></td>' +
      '<td>' + serviceBadge + '</td>' +
      '<td>' + healthBadge + '</td>' +
      '<td><div class="font-mono text-xs break-all">' + escapeHtml(brain.mcp_url) + '</div>' +
      '<div class="font-mono text-[10px] opacity-60">' + escapeHtml(brain.mcp_server_name) + '</div></td>' +
      '<td class="font-mono text-xs">127.0.0.1:' + escapeHtml(String(brain.port)) +
      '<div class="text-[10px] opacity-60">' + escapeHtml(brain.database_name) + ' / ' + escapeHtml(brain.writer_role) + '</div></td>' +
      '<td class="text-right whitespace-nowrap">' +
      '<button class="btn btn-ghost btn-xs" data-team-logs="' + project + '"><i data-lucide="scroll-text" class="size-3"></i>로그</button>' +
      '<button class="btn btn-warning btn-outline btn-xs" data-team-restart="' + project + '"><i data-lucide="rotate-ccw" class="size-3"></i>재시작</button>' +
      '</td></tr>';
  }

  /* ---------- 2. 만들기 ---------- */
  function openCreateModal() {
    getElement('team-create-form').reset();
    getElement('team-create-error').hidden = true;
    getElement('team-create-modal').showModal();
    getElement('team-project').focus();
  }

  async function submitCreateForm(event) {
    event.preventDefault();
    const submitButton = getElement('team-create-submit');
    const errorText = getElement('team-create-error');
    errorText.hidden = true;
    submitButton.disabled = true;
    submitButton.textContent = '만드는 중이에요... (최대 몇 분)';
    try {
      const response = await apiFetch(API, {
        method: 'POST',
        body: JSON.stringify({ project: getElement('team-project').value.trim(), writer_password: getElement('team-writer-password').value }),
      });
      const responseBody = await readResponseBody(response);
      getElement('team-writer-password').value = '';
      if (!response.ok) {
        // 중간 실패라도 새 쓰기 계정 비번은 결과 창으로 1번 보여 줌 (다시 받을 수 없음)
        if (responseBody.writer_secret) openResultModal(responseBody, true);
        throw new Error(describeFailure(responseBody, '팀 브레인을 만들지 못했어요'));
      }
      getElement('team-create-modal').close();
      openResultModal(responseBody, false);
      showToast(responseBody.brain.project + ' 팀 브레인을 만들었어요', 'success');
    } catch (error) {
      errorText.textContent = error.message;
      errorText.hidden = false;
    } finally {
      submitButton.disabled = false;
      submitButton.textContent = '만들기';
      loadTeams();
    }
  }

  function openResultModal(responseBody, isPartialFailure) {
    const steps = responseBody.steps || {};
    getElement('team-result-title').textContent = isPartialFailure
      ? '팀 브레인을 만들다 멈췄어요. 원인을 고친 뒤 다시 만들기를 누르면 이어서 해요'
      : (responseBody.brain.project + ' 팀 브레인을 만들었어요');
    getElement('team-result-steps').innerHTML = Object.keys(steps).map(function (stepName) {
      return '<li><span class="font-semibold">' + escapeHtml(STEP_LABELS[stepName] || stepName) + '</span> : ' +
        escapeHtml(STEP_RESULT_LABELS[steps[stepName]] || steps[stepName]) + '</li>';
    }).join('');
    const writerSecret = responseBody.writer_secret;
    getElement('team-writer-secret').hidden = !writerSecret;
    getElement('team-writer-connection-url').value = writerSecret ? writerSecret.sync_connection_url : '';
    getElement('team-result-modal').showModal();
  }

  /* ---------- 3. 재시작·로그 ---------- */
  async function restartTeam(project, button) {
    if (!window.confirm(project + ' 팀 브레인 서버를 재시작할까요?\n\n재시작하는 몇 초 동안 팀원의 연결이 잠깐 끊겨요.')) return;
    button.disabled = true;
    try {
      const response = await apiFetch(API + '/' + encodeURIComponent(project) + '/control/restart', { method: 'POST', body: '{}' });
      const responseBody = await readResponseBody(response);
      if (!response.ok) throw new Error(describeFailure(responseBody, '재시작하지 못했어요'));
      showToast(responseBody.summary || '재시작했어요', 'success');
    } catch (error) {
      showToast(escapeHtml(error.message), 'error');
    } finally {
      button.disabled = false;
      loadTeams();
    }
  }

  async function openLogs(project) {
    getElement('team-log-title').textContent = project + ' 팀 브레인 로그 (끝 ' + LOG_LINES + '줄)';
    getElement('team-log-container').textContent = '불러오는 중이에요...';
    getElement('team-log-modal').showModal();
    try {
      const response = await apiFetch(API + '/' + encodeURIComponent(project) + '/logs?lines=' + LOG_LINES);
      const responseBody = await readResponseBody(response);
      if (!response.ok) throw new Error(describeFailure(responseBody, '로그를 불러오지 못했어요'));
      getElement('team-log-container').textContent = (responseBody.logs || []).join('\n') || '로그가 비어 있어요';
    } catch (error) {
      getElement('team-log-container').textContent = error.message;
    }
  }

  // 결과 창 닫힘 > 비번이 담긴 칸 비움
  function clearResultModal() {
    getElement('team-writer-connection-url').value = '';
  }

  /* ---------- 초기화 ---------- */
  document.addEventListener('DOMContentLoaded', function () {
    loadTeams();
    setInterval(loadTeams, LIST_REFRESH_MILLISECONDS);
    getElement('team-refresh').addEventListener('click', loadTeams);
    getElement('team-create-open').addEventListener('click', openCreateModal);
    getElement('team-create-form').addEventListener('submit', submitCreateForm);
    document.querySelectorAll('[data-close-team-modal]').forEach(function (button) {
      button.addEventListener('click', function () { getElement('team-create-modal').close(); });
    });
    getElement('team-result-modal').addEventListener('close', clearResultModal);
  });
})();
