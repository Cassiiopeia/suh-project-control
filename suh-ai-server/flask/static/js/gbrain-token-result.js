/* gbrain MCP 토큰 발급 결과 창 (#207, #213): 원문 1회 표시 > 복사 > 닫으면 비움
   개인 브레인: 내 기기에 넣는 값(한 줄·설정 조각)을 펼쳐 보여 줌
   팀 브레인: 팀원에게 보낼 안내 + 전체 복사를 맨 위에, 직접 넣는 값은 접어 둠
   토큰 원문은 입력칸에만 두고 콘솔·저장소에 남기지 않음 */
(function () {
  // 원문이 들어가는 칸 (창을 닫으면 모두 비움)
  const SECRET_FIELD_IDS = ['token-secret-value', 'token-cli-command', 'token-config-snippet', 'token-team-guide-text'];
  const READ_ONLY_SCOPE_KEY = 'read';

  function el(id) { return document.getElementById(id); }

  // 결과 창에 넣을 값: 한 줄 명령, mcpServers 설정 조각
  function buildCliCommand(serverName, mcpUrl, secret) {
    return 'claude mcp add --scope user --transport http ' + serverName + ' ' + mcpUrl +
      ' --header "Authorization: Bearer ' + secret + '"';
  }

  function buildConfigSnippet(serverName, mcpUrl, secret) {
    const snippet = {};
    snippet[serverName] = { type: 'http', url: mcpUrl, headers: { Authorization: 'Bearer ' + secret } };
    // 바깥 중괄호를 빼고 한 단계 내어 씀 > mcpServers 안에 그대로 붙여 넣는 모양
    return JSON.stringify(snippet, null, 2).split('\n').slice(1, -1)
      .map(function (line) { return line.slice(2); }).join('\n');
  }

  // 팀원 안내: 처음 보는 팀원 기준 쉬운 말, 개인 gbrain 설정·훅·~/.gbrain 은 건드리지 않음
  function buildTeammateGuide(brainId, serverName, cliCommand, scopes) {
    const isReadOnly = (scopes || []).join(',') === READ_ONLY_SCOPE_KEY;
    return [
      '[' + brainId + ' 팀 브레인 연결 안내]',
      '',
      'Claude Code 에서 ' + brainId + ' 팀 기억(' + serverName + ')을 찾아 쓸 수 있게 연결해요.',
      'Claude Code 가 설치된 내 컴퓨터에서 해 주세요.',
      '',
      '1) 터미널을 열고 아래 한 줄을 그대로 붙여 넣은 뒤 Enter 를 눌러요.',
      cliCommand,
      '2) 열려 있는 Claude Code 를 모두 닫고 다시 열어요.',
      '3) Claude Code 에서 /mcp 를 입력해 ' + serverName + ' 이 connected 로 보이면 끝이에요.',
      '',
      '알아 두기',
      '- 이름이 ' + serverName + ' 이라서 쓰고 있는 개인 gbrain 과 따로 붙어요. 둘 다 그대로 함께 써요.',
      '- 이 한 줄은 Claude Code 에 연결을 하나 더할 뿐이에요. 개인 gbrain 설정, 훅, ~/.gbrain 은 그대로예요.',
      isReadOnly
        ? '- 읽기 전용 토큰이에요. 팀 기억을 찾아 읽을 수 있고, 내용은 프로젝트 레포의 knowledge/ 폴더에서 와요.'
        : '- 읽기 + 쓰기 토큰이에요. 여기에 저장한 내용은 모든 팀원이 함께 봐요.',
      '- 이미 있다고(already exists) 나오면 claude mcp remove ' + serverName + ' -s user 를 실행하고 1) 을 다시 해요.',
      '- 연결이 401 로 실패하면 토큰을 새로 받아야 해요. 관리자에게 알려 주세요.',
      '- 토큰은 비밀번호와 같아요. 내 컴퓨터에만 넣어 두고, 잃어버리면 관리자에게 알려 주세요.',
    ].join('\n');
  }

  // 개인·팀 브레인에 따라 안내 문구·펼침 상태 전환
  function applyBrainKind(isTeam) {
    el('token-team-guide').hidden = !isTeam;
    el('token-self-install').open = !isTeam;
    el('token-self-install-summary').textContent = isTeam
      ? '직접 넣는 값 보기 (팀원이 한 줄 대신 설정 파일을 쓸 때)'
      : '이 기기에 넣는 값';
    el('token-secret-warning').textContent = isTeam
      ? '이 토큰은 지금만 볼 수 있어요. 창을 닫기 전에 아래 팀원 안내를 복사해서 그 팀원에게 보내 주세요.'
      : '이 토큰은 지금만 볼 수 있어요. 창을 닫기 전에 먼저 복사해 두세요. 잃어버리면 이 토큰을 폐기하고 새로 만들면 돼요.';
    el('token-self-install-caution').textContent = isTeam
      ? '토큰은 비밀번호와 같아요. 그 팀원에게 1:1 로만 전하고, 팀원은 자기 컴퓨터에만 넣어요.'
      : '토큰은 비밀번호와 같아요. 이 기기의 Claude Code 에만 넣어 두세요.';
    el('token-secret-close').textContent = isTeam ? '팀원에게 보냈어요, 닫기' : '다 넣었어요, 닫기';
  }

  /* 발급 응답 > 결과 창 열기 (fallback: 목록에서 받은 주소·이름) */
  function openTokenResult(created, fallbackMcpUrl, fallbackServerName) {
    const mcpUrl = created.mcp_url || fallbackMcpUrl;
    const serverName = created.mcp_server_name || fallbackServerName;
    const cliCommand = buildCliCommand(serverName, mcpUrl, created.secret);
    el('token-secret-title').textContent = created.token.name + ' 토큰을 만들었어요';
    el('token-secret-value').value = created.secret;
    el('token-cli-command').value = cliCommand;
    el('token-config-snippet').value = buildConfigSnippet(serverName, mcpUrl, created.secret);
    document.querySelectorAll('[data-mcp-server-name]').forEach(function (span) { span.textContent = serverName; });
    el('token-team-guide-text').value = created.is_team
      ? buildTeammateGuide(created.brain, serverName, cliCommand, created.token.scopes) : '';
    applyBrainKind(!!created.is_team);
    el('token-secret-modal').showModal();
  }

  // 결과 창 닫힘 > 원문이 담긴 칸 모두 비움 (다시 열어도 볼 수 없게)
  function clearTokenResult() {
    SECRET_FIELD_IDS.forEach(function (id) { el(id).value = ''; });
  }

  // 복사 (clipboard API 없으면 칸 선택 > execCommand), 결과 창·팀 브레인 결과 창 공용
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
      showToast('복사하지 못했어요. 칸을 직접 선택해서 복사해 주세요 [copy_failed]', 'error');
    }
  }

  window.gbrainTokenResult = { open: openTokenResult };

  document.addEventListener('DOMContentLoaded', function () {
    document.querySelectorAll('[data-copy-target]').forEach(function (button) {
      button.addEventListener('click', function () { copyFieldValue(button.dataset.copyTarget); });
    });
    el('token-secret-modal').addEventListener('close', clearTokenResult);
  });
})();
