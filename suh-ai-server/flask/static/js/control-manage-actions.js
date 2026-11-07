/* 관제소 서비스 관리 동작: API 호출(PATCH·POST·DELETE) > 실패 사유 안내 > 성공 시 목록 재조회
   window.ControlManageActions 로 노출 (화면 렌더는 control-manage.js) */
(function () {
  const API = '../control';
  // 오류 코드 > 안내 문구
  const ERROR_MESSAGES = {
    invalid: '입력값을 확인하세요',
    unknown_service: '등록되지 않은 서비스입니다',
    unknown_project: '등록되지 않은 프로젝트입니다',
    duplicate_id: '이미 있는 id입니다',
    registry_service: '등록 파일 서비스는 삭제할 수 없습니다. "추적 안 함"으로 바꾸세요',
    external_check_limit: '외부 점검 상한을 넘습니다. 다른 서비스를 "추적 안 함"으로 바꾸세요',
    cloudflare_not_configured: 'CLOUDFLARE_API_TOKEN이 설정되지 않았습니다',
    dns_lookup_failed: 'Cloudflare 조회에 실패했습니다',
    unavailable: '관제소를 사용할 수 없습니다',
    discord_not_configured: '디스코드 봇이 설정되지 않았습니다',
    discord_not_synced: '디스코드 동기화를 먼저 실행하세요 (상태 채널·역할 없음)',
    discord_failed: '디스코드 요청에 실패했습니다',
  };
  // 서비스 id 규칙 (서버 검증과 같음)
  const IDENTIFIER_PATTERN = /^[a-z0-9][a-z0-9-]{1,40}$/;
  const IDENTIFIER_MAX_LENGTH = 41;

  async function sendJson(method, path, payload) {
    const response = await apiFetch(API + path, { method: method, body: payload ? JSON.stringify(payload) : undefined });
    let data = {};
    try { data = await response.json(); } catch (parseError) { /* 본문 없음 */ }
    return { ok: response.ok, status: response.status, data: data };
  }

  function describeFailure(result) {
    const message = ERROR_MESSAGES[result.data.error] || ('요청에 실패했습니다 (' + result.status + ')');
    const fields = result.data.fields ? ' : ' + result.data.fields.join(', ') : '';
    return message + fields;
  }

  function reloadManage() {
    if (window.ControlManage) window.ControlManage.reload();
  }

  // 요청 1건: 실패 안내 > 성공 시 문구·재조회 (실패해도 재조회로 화면 값 되돌림)
  async function run(method, path, payload, successMessage) {
    try {
      const result = await sendJson(method, path, payload);
      if (!result.ok) { showToast(describeFailure(result), 'error'); reloadManage(); return result; }
      if (successMessage) showToast(successMessage, 'success');
      reloadManage();
      return result;
    } catch (error) {
      console.warn('control manage action failed:', error);
      showToast('요청에 실패했습니다', 'error');
      return { ok: false, status: 0, data: {} };
    }
  }

  function patchService(serviceId, changes, successMessage) {
    return run('PATCH', '/services/' + encodeURIComponent(serviceId), changes, successMessage || '저장했습니다');
  }

  function patchProject(projectId, changes, successMessage) {
    return run('PATCH', '/projects/' + encodeURIComponent(projectId), changes, successMessage || '저장했습니다');
  }

  function deleteService(serviceId) {
    return run('DELETE', '/services/' + encodeURIComponent(serviceId), null, '삭제했습니다');
  }

  function createService(values) {
    return run('POST', '/services', values, '서비스를 추가했습니다');
  }

  function createProject(values) {
    return run('POST', '/projects', values, '프로젝트를 추가했습니다');
  }

  // 순서 위·아래: 묶음 전체를 0부터 다시 매기고 바뀐 항목만 PATCH (kind: 'services' | 'projects')
  async function moveItem(kind, items, index, direction) {
    const targetIndex = index + direction;
    if (targetIndex < 0 || targetIndex >= items.length) return;
    const reordered = items.slice();
    const moved = reordered.splice(index, 1)[0];
    reordered.splice(targetIndex, 0, moved);
    const changedItems = reordered.filter(function (item, order) { return item.sort_order !== order; });
    for (const item of changedItems) {
      const result = await sendJson('PATCH', '/' + kind + '/' + encodeURIComponent(item.id),
        { sort_order: reordered.indexOf(item) });
      if (!result.ok) { showToast(describeFailure(result), 'error'); break; }
    }
    reloadManage();
  }

  // DNS 이름 > 서비스 id ("blog.suhsaechan.kr" + zone > "blog", 점은 -로)
  function toServiceIdentifier(hostname, zoneName) {
    const label = hostname === zoneName ? hostname : hostname.replace(new RegExp('\\.' + zoneName.replace(/\./g, '\\.') + '$'), '');
    const identifier = label.toLowerCase().replace(/[^a-z0-9-]+/g, '-').replace(/^-+|-+$/g, '').slice(0, IDENTIFIER_MAX_LENGTH);
    return IDENTIFIER_PATTERN.test(identifier) ? identifier : null;
  }

  async function loadDnsCandidates() {
    try {
      const result = await sendJson('GET', '/dns-candidates');
      if (!result.ok) return { candidates: [], message: describeFailure(result) + (result.data.reason ? ' (' + result.data.reason + ')' : '') };
      return { candidates: result.data.candidates, zone: result.data.zone, message: null };
    } catch (error) {
      console.warn('control dns candidates failed:', error);
      return { candidates: [], message: '요청에 실패했습니다' };
    }
  }

  // DNS 후보 1개 추가: 비공개·추적함, 주소 https://{hostname}/
  function importDnsCandidate(candidate, zoneName, projectId) {
    const identifier = toServiceIdentifier(candidate.hostname, zoneName);
    if (!identifier) { showToast('id로 바꿀 수 없는 이름입니다: ' + candidate.hostname, 'error'); return Promise.resolve({ ok: false }); }
    return createService({
      id: identifier, project_id: projectId, name: candidate.hostname,
      external_url: 'https://' + candidate.hostname + '/', is_public: false,
    });
  }

  window.ControlManageActions = {
    sendJson, describeFailure, patchService, patchProject, deleteService, createService, createProject,
    moveItem, loadDnsCandidates, importDnsCandidate,
  };
})();
