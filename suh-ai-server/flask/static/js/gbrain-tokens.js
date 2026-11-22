/* gbrain MCP 기기 토큰 카드 (#207): 목록 > 새 기기 연결(발급) > 결과 창 1회 표시 > 폐기
   API: ../gbrain/tokens (GET 목록, POST 발급), ../gbrain/tokens/{id}/revoke (POST 폐기), 모두 brain 지정 (#210)
   브레인 선택지: gbrain-teams.js 가 보내는 'gbrain-teams-loaded' 이벤트로 채움
   토큰 원문은 결과 창 입력칸에만 두고 콘솔·저장소에 남기지 않음, 창을 닫으면 비움 */
(function () {
  const API = '../gbrain/tokens';
  const DEFAULT_MCP_URL = 'https://ai.suhsaechan.kr/mcp';
  // 개인 브레인 id·Claude Code 설정 이름 (팀 브레인은 서버가 gbrain-<project> 를 알려 줌)
  const PERSONAL_BRAIN_ID = 'personal';
  const PERSONAL_MCP_SERVER_NAME = 'gbrain';
  // 이 시간 안에 쓴 토큰은 폐기 확인 문구를 더 강하게 (24시간)
  const RECENT_USE_MILLISECONDS = 24 * 60 * 60 * 1000;

  // 권한 목록 > 표시 이름
  const SCOPE_LABELS = { 'read,write': '읽기 + 쓰기', read: '읽기 전용' };

  let mcpUrl = DEFAULT_MCP_URL;
  let mcpServerName = PERSONAL_MCP_SERVER_NAME;
  let defaultScopePreset = 'read_write';

  function selectedBrain() {
    return el('token-brain-select').value || PERSONAL_BRAIN_ID;
  }

  function el(id) { return document.getElementById(id); }

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

  /* ---------- 1. 목록 ---------- */
  async function loadTokens() {
    const tableBody = el('token-table-body');
    try {
      const response = await apiFetch(API + '?brain=' + encodeURIComponent(selectedBrain()) + '&t=' + Date.now());
      const result = await readJson(response);
      if (!response.ok) throw new Error(describeFailure(result, '토큰 목록을 불러오지 못했어요'));
      mcpUrl = result.mcp_url || DEFAULT_MCP_URL;
      mcpServerName = result.mcp_server_name || PERSONAL_MCP_SERVER_NAME;
      defaultScopePreset = result.default_scope_preset || 'read_write';
      el('token-mcp-url').textContent = mcpUrl;
      el('token-mcp-server-name').textContent = mcpServerName;
      el('token-team-hint').hidden = !result.is_team;
      renderTokens(result.tokens || []);
    } catch (error) {
      tableBody.innerHTML = '<tr><td colspan="6" class="text-center text-error py-6">' + escapeHtml(error.message) + '</td></tr>';
    }
  }

  function renderTokens(tokens) {
    const tableBody = el('token-table-body');
    if (!tokens.length) {
      tableBody.innerHTML = '<tr><td colspan="6" class="text-center opacity-50 py-6">아직 만든 토큰이 없어요. "새 기기 연결"로 시작해 보세요.</td></tr>';
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
      ? '<span class="badge badge-success badge-sm">사용 중</span>'
      : '<span class="badge badge-ghost badge-sm">폐기됨</span>';
    const revokeButton = token.is_active
      ? '<button class="btn btn-error btn-outline btn-xs" data-revoke-token-id="' + escapeHtml(token.id) + '">' +
        '<i data-lucide="ban" class="size-3"></i>폐기</button>'
      : '';
    return '<tr class="' + (token.is_active ? '' : 'opacity-50') + '">' +
      '<td><div class="font-mono text-xs font-semibold">' + escapeHtml(token.name) + '</div>' +
      '<div class="font-mono text-[10px] opacity-50">' + escapeHtml(token.id) + '</div></td>' +
      '<td class="text-xs">' + escapeHtml(describeScopes(token.scopes)) + '</td>' +
      '<td>' + statusBadge + '</td>' +
      '<td class="text-xs whitespace-nowrap">' + escapeHtml(formatDateTime(token.created_at)) + '</td>' +
      '<td class="text-xs whitespace-nowrap">' + escapeHtml(token.last_used_at ? formatDateTime(token.last_used_at) : '안 씀') + '</td>' +
      '<td class="text-right">' + revokeButton + '</td>' +
      '</tr>';
  }

  /* ---------- 2. 발급 ---------- */
  function openCreateModal() {
    el('token-create-form').reset();
    // 기본 권한: 팀 브레인 읽기 전용, 개인 읽기+쓰기
    const defaultScopeInput = document.querySelector('input[name="token-scope-preset"][value="' + defaultScopePreset + '"]');
    if (defaultScopeInput) defaultScopeInput.checked = true;
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
          name: el('token-device-name').value.trim(), brain: selectedBrain(),
          scope_preset: scopeInput ? scopeInput.value : defaultScopePreset,
        }),
      });
      const result = await readJson(response);
      if (!response.ok) throw new Error(describeFailure(result, '토큰을 만들지 못했어요'));
      el('token-create-modal').close();
      openSecretModal(result);
      showToast(result.token.name + ' 토큰을 만들었어요', 'success');
      loadTokens();
    } catch (error) {
      errorText.textContent = error.message;
      errorText.hidden = false;
    } finally {
      submitButton.disabled = false;
    }
  }

  // 기기에 넣을 값 3개: 토큰, claude mcp add 한 줄, mcpServers 설정 조각 (+ 팀 브레인이면 팀원 안내)
  function openSecretModal(created) {
    const usedMcpUrl = created.mcp_url || mcpUrl;
    const usedServerName = created.mcp_server_name || mcpServerName;
    const authorizationHeader = 'Authorization: Bearer ' + created.secret;
    const cliCommand = 'claude mcp add --scope user --transport http ' + usedServerName + ' ' +
      usedMcpUrl + ' --header "' + authorizationHeader + '"';
    el('token-secret-title').textContent = created.token.name + ' 토큰을 만들었어요';
    el('token-secret-value').value = created.secret;
    el('token-cli-command').value = cliCommand;
    document.querySelectorAll('[data-mcp-server-name]').forEach(function (span) { span.textContent = usedServerName; });
    el('token-team-guide').hidden = !created.is_team;
    if (created.is_team) {
      el('token-team-guide-text').value = buildTeammateGuide(created.brain, usedServerName, cliCommand, created.token.scopes);
    }
    const configSnippet = {};
    configSnippet[usedServerName] = {
      type: 'http', url: usedMcpUrl, headers: { Authorization: 'Bearer ' + created.secret },
    };
    // 바깥 중괄호를 빼고 한 단계 내어 씀 > mcpServers 안에 그대로 붙여 넣는 모양
    el('token-config-snippet').value = JSON.stringify(configSnippet, null, 2).split('\n').slice(1, -1)
      .map(function (line) { return line.slice(2); }).join('\n');
    el('token-secret-modal').showModal();
  }

  // 팀원 안내: 개인 gbrain 과 나란히 쓰는 MCP 서버 추가 (개인 설정·훅·~/.gbrain 은 건드리지 않음)
  function buildTeammateGuide(brainId, serverName, cliCommand, scopes) {
    const isReadOnly = (scopes || []).join(',') === 'read';
    return [
      '[' + brainId + ' 팀 브레인 연결 안내]',
      '',
      '1) 터미널에 아래 한 줄을 붙여 넣고 Enter 를 눌러요.',
      cliCommand,
      '2) 열려 있는 Claude Code 를 모두 닫고 다시 열어요.',
      '3) Claude Code 에서 /mcp 를 입력해 ' + serverName + ' 이 connected 로 보이면 끝이에요.',
      '',
      '알아 두기',
      '- 이름이 ' + serverName + ' 이라서 개인 gbrain(HTTP 든 로컬 gbrain serve 든)과 겹치지 않아요. 둘 다 함께 써요.',
      '  Claude 도구 이름도 mcp__gbrain__* 와 mcp__' + serverName + '__* 로 나뉘어요.',
      '- 이 한 줄은 Claude Code 설정에 MCP 서버를 하나 더할 뿐이에요. 개인 gbrain 설정, 훅, ~/.gbrain, mounts, sources 는 바뀌지 않아요.',
      isReadOnly
        ? '- 읽기 전용 토큰이라 팀 브레인을 찾기만 하고 저장은 안 돼요. 팀 브레인 내용은 프로젝트 레포의 knowledge/ 폴더에서 와요.'
        : '- 읽기 + 쓰기 토큰이에요. 팀 브레인에 저장하면 모든 팀원이 보게 돼요.',
      '- 이미 ' + serverName + ' 이 있다고 나오면: claude mcp remove ' + serverName + ' -s user 를 실행하고 다시 붙여 넣어요.',
      '- 토큰은 비밀번호와 같아요. 다른 곳에 붙여 넣지 말고, 잃어버리면 관리자에게 폐기·재발급을 요청해요.',
    ].join('\n');
  }

  // 결과 창 닫힘 > 원문이 담긴 칸 모두 비움 (다시 열어도 볼 수 없게)
  function clearSecretModal() {
    ['token-secret-value', 'token-cli-command', 'token-config-snippet', 'token-team-guide-text']
      .forEach(function (id) { el(id).value = ''; });
  }

  // 팀 브레인 목록 > 브레인 선택지 (고른 값 유지, 사라진 브레인이면 개인으로)
  function renderBrainOptions(brains) {
    const select = el('token-brain-select');
    const previousValue = select.value;
    select.innerHTML = '<option value="' + PERSONAL_BRAIN_ID + '">개인 브레인 (gbrain)</option>' +
      brains.map(function (brain) {
        return '<option value="' + escapeHtml(brain.project) + '">' + escapeHtml(brain.project) +
          ' 팀 (' + escapeHtml(brain.mcp_server_name) + ')</option>';
      }).join('');
    const hasPrevious = Array.prototype.some.call(select.options, function (option) { return option.value === previousValue; });
    select.value = hasPrevious ? previousValue : PERSONAL_BRAIN_ID;
    if (select.value !== previousValue) loadTokens();
  }

  // 복사 (clipboard API 없으면 칸 선택 > execCommand)
  async function copyFieldValue(fieldId) {
    const field = el(fieldId);
    try {
      if (navigator.clipboard && window.isSecureContext) {
        await navigator.clipboard.writeText(field.value);
      } else {
        field.select();
        document.execCommand('copy');
      }
      showToast('복사했어요', 'success');
    } catch (error) {
      console.warn('gbrain token copy failed');  // 값은 콘솔에 남기지 않음
      showToast('복사하지 못했어요. 직접 선택해서 복사해 주세요', 'error');
    }
  }

  /* ---------- 3. 폐기 ---------- */
  async function revokeToken(token, button) {
    const recentUseWarning = isRecentlyUsed(token)
      ? '\n\n최근 24시간 안에 쓴 토큰이에요. 지금 이 토큰을 쓰는 컴퓨터가 있다면 그 컴퓨터의 gbrain 연결이 바로 끊겨요.'
      : '';
    const confirmText = '"' + token.name + '" 토큰을 폐기할까요?\n\n폐기하면 바로 적용돼서 이 토큰으로는 다시 접속할 수 없어요. ' +
      '되돌릴 수 없고, 필요하면 새 토큰을 만들면 돼요.' + recentUseWarning;
    if (!window.confirm(confirmText)) return;
    button.disabled = true;
    try {
      const response = await apiFetch(API + '/' + encodeURIComponent(token.id) + '/revoke',
        { method: 'POST', body: JSON.stringify({ brain: selectedBrain() }) });
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
    loadTokens();
    el('token-refresh').addEventListener('click', loadTokens);
    el('token-brain-select').addEventListener('change', loadTokens);
    document.addEventListener('gbrain-teams-loaded', function (event) { renderBrainOptions(event.detail.brains || []); });
    el('token-create-open').addEventListener('click', openCreateModal);
    el('token-create-form').addEventListener('submit', submitCreateForm);
    document.querySelectorAll('[data-close-token-modal]').forEach(function (button) {
      button.addEventListener('click', function () { el('token-create-modal').close(); });
    });
    document.querySelectorAll('[data-copy-target]').forEach(function (button) {
      button.addEventListener('click', function () { copyFieldValue(button.dataset.copyTarget); });
    });
    el('token-secret-modal').addEventListener('close', clearSecretModal);
  });
})();
