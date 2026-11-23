/* gbrain MCP 기기 토큰 카드 (#207, #210, #213): 브레인 선택 > 목록 > 새 토큰(발급) > 결과 창(gbrain-token-result.js) > 폐기
   API: ../gbrain/tokens (GET 목록, POST 발급), ../gbrain/tokens/{id}/revoke (POST 폐기), 모두 brain 지정
   브레인 선택지: gbrain-teams.js 가 보내는 'gbrain-teams-loaded' 이벤트로 채움
   브레인을 바꾸면 그 브레인 기준(이름·주소·기본 권한)으로 바로 전환, 늦게 온 이전 목록 응답은 버림 */
(function () {
  const API = '../gbrain/tokens';
  const DEFAULT_MCP_URL = 'https://ai.suhsaechan.kr/mcp';
  // 개인 브레인 id·Claude Code 설정 이름 (팀 브레인은 서버가 gbrain-<project> 를 알려 줌)
  const PERSONAL_BRAIN_ID = 'personal';
  const PERSONAL_MCP_SERVER_NAME = 'gbrain';
  // 기본 권한: 개인 읽기 + 쓰기, 팀 읽기 전용 (서버 default_scope_preset 과 같은 값)
  const PERSONAL_DEFAULT_SCOPE_PRESET = 'read_write';
  const TEAM_DEFAULT_SCOPE_PRESET = 'read_only';
  // 이 시간 안에 쓴 토큰은 폐기 확인 문구를 더 강하게 (24시간)
  const RECENT_USE_MILLISECONDS = 24 * 60 * 60 * 1000;

  // 권한 목록 > 표시 이름
  const SCOPE_LABELS = { 'read,write': '읽기 + 쓰기', read: '읽기 전용' };

  // 지금 고른 브레인 기준 값 (목록 응답이 오면 서버 값으로 갱신)
  let brainContext = describeBrainContext(PERSONAL_BRAIN_ID);
  // 팀 브레인 id > {mcp_url, mcp_server_name} (팀 목록 이벤트로 채움)
  let teamBrainById = {};
  // 목록 요청 순번: 마지막 요청의 응답만 화면에 반영
  let latestListRequestNumber = 0;

  function el(id) { return document.getElementById(id); }

  function selectedBrain() {
    return el('token-brain-select').value || PERSONAL_BRAIN_ID;
  }

  async function readJson(response) {
    try { return await response.json(); } catch (e) { return {}; }
  }

  // 실패 문구 + 에러 코드 (화면 문구 규칙: 오류에는 코드 함께)
  function describeFailure(result, fallbackMessage) {
    return (result.error || fallbackMessage) + (result.code ? ' [' + result.code + ']' : '');
  }

  const DATE_TIME_FORMAT = new Intl.DateTimeFormat('ko-KR', {
    timeZone: 'Asia/Seoul', year: 'numeric', month: '2-digit', day: '2-digit',
    hour: '2-digit', minute: '2-digit', hour12: false,
  });

  function formatDateTime(value) {
    if (!value) return '-';
    const date = new Date(value);
    return isNaN(date.getTime()) ? '-' : DATE_TIME_FORMAT.format(date);
  }

  function describeScopes(scopes) {
    const scopeKey = (scopes || []).join(',');
    return SCOPE_LABELS[scopeKey] || scopeKey || '-';
  }

  function isRecentlyUsed(token) {
    if (!token.last_used_at) return false;
    return Date.now() - new Date(token.last_used_at).getTime() < RECENT_USE_MILLISECONDS;
  }

  /* ---------- 0. 브레인 기준 값 ---------- */
  // 브레인 id > 화면에 쓸 이름·주소·기본 권한 (팀 값은 팀 목록에서, 없으면 목록 응답이 채움)
  function describeBrainContext(brainId) {
    if (brainId === PERSONAL_BRAIN_ID) {
      return { brainId: brainId, isTeam: false, mcpUrl: DEFAULT_MCP_URL, mcpServerName: PERSONAL_MCP_SERVER_NAME,
        defaultScopePreset: PERSONAL_DEFAULT_SCOPE_PRESET, label: '개인 브레인' };
    }
    const teamBrain = teamBrainById[brainId] || {};
    return { brainId: brainId, isTeam: true, mcpUrl: teamBrain.mcp_url || '', mcpServerName: teamBrain.mcp_server_name || '',
      defaultScopePreset: TEAM_DEFAULT_SCOPE_PRESET, label: brainId + ' 팀 브레인' };
  }

  // 카드 설명 문구·발급 버튼을 지금 브레인 기준으로
  function renderBrainContext() {
    el('token-mcp-url').textContent = brainContext.mcpUrl || '-';
    el('token-mcp-server-name').textContent = brainContext.mcpServerName || '-';
    el('token-personal-hint').hidden = brainContext.isTeam;
    el('token-team-hint').hidden = !brainContext.isTeam;
    el('token-create-open-label').textContent = brainContext.isTeam ? '팀원 토큰 만들기' : '새 기기 연결';
  }

  // 브레인 변경 > 이전 브레인 표·기본 권한을 바로 치우고 새로 불러옴
  function onBrainSelected() {
    brainContext = describeBrainContext(selectedBrain());
    renderBrainContext();
    loadTokens();
  }

  /* ---------- 1. 목록 ---------- */
  async function loadTokens() {
    const requestNumber = ++latestListRequestNumber;
    const requestedBrain = selectedBrain();
    const tableBody = el('token-table-body');
    // 응답 전까지 발급 잠금 + 이전 브레인 표 숨김 (다른 브레인 기본값·폐기 버튼으로 잘못 누르지 않게)
    el('token-create-open').disabled = true;
    tableBody.innerHTML = '<tr><td colspan="6" class="text-center opacity-50 py-6">토큰 목록을 불러오는 중이에요...</td></tr>';
    try {
      const response = await apiFetch(API + '?brain=' + encodeURIComponent(requestedBrain) + '&t=' + Date.now());
      const result = await readJson(response);
      if (requestNumber !== latestListRequestNumber) return;  // 그사이 브레인을 바꿈 > 버림
      if (!response.ok) throw new Error(describeFailure(result, '토큰 목록을 불러오지 못했어요'));
      brainContext = Object.assign(describeBrainContext(requestedBrain), {
        mcpUrl: result.mcp_url || brainContext.mcpUrl,
        mcpServerName: result.mcp_server_name || brainContext.mcpServerName,
        defaultScopePreset: result.default_scope_preset || brainContext.defaultScopePreset,
        isTeam: !!result.is_team,
      });
      renderBrainContext();
      renderTokens(result.tokens || []);
      el('token-create-open').disabled = false;
    } catch (error) {
      if (requestNumber !== latestListRequestNumber) return;
      tableBody.innerHTML = '<tr><td colspan="6" class="text-center text-error py-6">' + escapeHtml(error.message) + '</td></tr>';
    }
  }

  function renderTokens(tokens) {
    const tableBody = el('token-table-body');
    if (!tokens.length) {
      const emptyHint = brainContext.isTeam ? '"팀원 토큰 만들기"로 팀원마다 하나씩 만들어 보세요.' : '"새 기기 연결"로 시작해 보세요.';
      tableBody.innerHTML = '<tr><td colspan="6" class="text-center opacity-50 py-6">아직 만든 토큰이 없어요. ' + emptyHint + '</td></tr>';
      return;
    }
    tableBody.innerHTML = tokens.map(renderTokenRow).join('');
    tableBody.querySelectorAll('[data-revoke-token-id]').forEach(function (button) {
      button.addEventListener('click', function () {
        const token = tokens.find(function (item) { return item.id === button.dataset.revokeTokenId; });
        if (token) revokeToken(token, button);
      });
    });
    if (window.lucide) lucide.createIcons();
  }

  function renderTokenRow(token) {
    const statusBadge = token.is_active
      ? '<span class="badge badge-success badge-sm whitespace-nowrap">사용 중</span>'
      : '<span class="badge badge-ghost badge-sm whitespace-nowrap">폐기됨</span>';
    const revokeButton = token.is_active
      ? '<button class="btn btn-error btn-outline btn-xs whitespace-nowrap" data-revoke-token-id="' + escapeHtml(token.id) + '">' +
        '<i data-lucide="ban" class="size-3"></i>폐기</button>'
      : '';
    return '<tr class="' + (token.is_active ? '' : 'opacity-50') + '">' +
      '<td><div class="font-mono text-xs font-semibold break-all">' + escapeHtml(token.name) + '</div>' +
      '<div class="font-mono text-[10px] opacity-50 break-all">' + escapeHtml(token.id) + '</div></td>' +
      '<td class="text-xs whitespace-nowrap">' + escapeHtml(describeScopes(token.scopes)) + '</td>' +
      '<td>' + statusBadge + '</td>' +
      '<td class="text-xs whitespace-nowrap">' + escapeHtml(formatDateTime(token.created_at)) + '</td>' +
      '<td class="text-xs whitespace-nowrap">' + escapeHtml(token.last_used_at ? formatDateTime(token.last_used_at) : '아직 안 씀') + '</td>' +
      '<td class="text-right">' + revokeButton + '</td>' +
      '</tr>';
  }

  /* ---------- 2. 발급 ---------- */
  // 발급 창: 만들 곳(브레인)·이름 안내·기본 권한을 지금 브레인 기준으로
  function openCreateModal() {
    el('token-create-form').reset();
    el('token-create-title').textContent = brainContext.isTeam ? '팀원 토큰 만들기' : '새 기기 연결';
    el('token-create-target').textContent = brainContext.label + ' (' + (brainContext.mcpServerName || '-') + ')';
    el('token-name-label').textContent = brainContext.isTeam ? '팀원·기기 이름' : '기기 이름';
    el('token-device-name').placeholder = brainContext.isTeam ? '예: kim-macbook' : '예: work-macbook';
    document.querySelectorAll('[data-scope-default-badge]').forEach(function (badge) {
      badge.hidden = badge.dataset.scopeDefaultBadge !== brainContext.defaultScopePreset;
    });
    const defaultScopeInput = document.querySelector('input[name="token-scope-preset"][value="' + brainContext.defaultScopePreset + '"]');
    if (defaultScopeInput) defaultScopeInput.checked = true;
    el('token-create-modal').dataset.brain = brainContext.brainId;
    el('token-create-error').hidden = true;
    el('token-create-modal').showModal();
    el('token-device-name').focus();
  }

  async function submitCreateForm(event) {
    event.preventDefault();
    const submitButton = el('token-create-submit');
    const errorText = el('token-create-error');
    const scopeInput = document.querySelector('input[name="token-scope-preset"]:checked');
    errorText.hidden = true;
    submitButton.disabled = true;
    try {
      const response = await apiFetch(API, {
        method: 'POST',
        body: JSON.stringify({
          // 창을 연 때의 브레인으로 발급 (창이 열린 뒤 선택이 바뀌어도 같은 곳)
          name: el('token-device-name').value.trim(), brain: el('token-create-modal').dataset.brain,
          scope_preset: scopeInput ? scopeInput.value : brainContext.defaultScopePreset,
        }),
      });
      const result = await readJson(response);
      if (!response.ok) throw new Error(describeFailure(result, '토큰을 만들지 못했어요'));
      el('token-create-modal').close();
      window.gbrainTokenResult.open(result, brainContext.mcpUrl, brainContext.mcpServerName);
      showToast(result.token.name + ' 토큰을 만들었어요', 'success');
      loadTokens();
    } catch (error) {
      errorText.textContent = error.message;
      errorText.hidden = false;
    } finally {
      submitButton.disabled = false;
    }
  }

  // 팀 브레인 목록 > 브레인 선택지 (고른 값 유지, 사라진 브레인이면 개인으로)
  function renderBrainOptions(brains) {
    const select = el('token-brain-select');
    const previousValue = select.value;
    teamBrainById = {};
    brains.forEach(function (brain) { teamBrainById[brain.project] = brain; });
    select.innerHTML = '<option value="' + PERSONAL_BRAIN_ID + '">개인 브레인 (' + PERSONAL_MCP_SERVER_NAME + ')</option>' +
      brains.map(function (brain) {
        return '<option value="' + escapeHtml(brain.project) + '">' + escapeHtml(brain.project) +
          ' 팀 (' + escapeHtml(brain.mcp_server_name) + ')</option>';
      }).join('');
    const hasPrevious = Array.prototype.some.call(select.options, function (option) { return option.value === previousValue; });
    select.value = hasPrevious ? previousValue : PERSONAL_BRAIN_ID;
    if (select.value !== previousValue) onBrainSelected();
  }

  /* ---------- 3. 폐기 ---------- */
  async function revokeToken(token, button) {
    const connectionOwner = brainContext.isTeam
      ? '그 팀원의 ' + brainContext.mcpServerName + ' 연결이'
      : '그 컴퓨터의 ' + PERSONAL_MCP_SERVER_NAME + ' 연결이';
    const recentUseWarning = isRecentlyUsed(token)
      ? '\n\n최근 24시간 안에 쓴 토큰이에요. 지금 이 토큰을 쓰고 있다면 ' + connectionOwner + ' 바로 끊겨요.'
      : '';
    const confirmText = '"' + token.name + '" 토큰을 폐기할까요?\n\n폐기하면 바로 적용돼서 ' + connectionOwner + ' 끊겨요. ' +
      '되돌릴 수 없고, 필요하면 새 토큰을 만들면 돼요.' + recentUseWarning;
    if (!window.confirm(confirmText)) return;
    button.disabled = true;
    try {
      const response = await apiFetch(API + '/' + encodeURIComponent(token.id) + '/revoke',
        { method: 'POST', body: JSON.stringify({ brain: brainContext.brainId }) });
      const result = await readJson(response);
      if (!response.ok) throw new Error(describeFailure(result, '토큰을 폐기하지 못했어요'));
      showToast(token.name + ' 토큰을 폐기했어요. 이제 이 토큰으로는 접속할 수 없어요', 'success');
    } catch (error) {
      showToast(escapeHtml(error.message), 'error');
    } finally {
      loadTokens();
    }
  }

  /* ---------- 초기화 ---------- */
  document.addEventListener('DOMContentLoaded', function () {
    renderBrainContext();
    loadTokens();
    el('token-refresh').addEventListener('click', loadTokens);
    el('token-brain-select').addEventListener('change', onBrainSelected);
    document.addEventListener('gbrain-teams-loaded', function (event) { renderBrainOptions(event.detail.brains || []); });
    el('token-create-open').addEventListener('click', openCreateModal);
    el('token-create-form').addEventListener('submit', submitCreateForm);
    document.querySelectorAll('[data-close-token-modal]').forEach(function (button) {
      button.addEventListener('click', function () { el('token-create-modal').close(); });
    });
  });
})();
