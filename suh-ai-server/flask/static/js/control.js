/* 관제소 관리자 페이지. base: /admin/control → API: ../control/*
   흐름: 진입 시 overview 조회 > 30초 폴링 > 표·요약 렌더 / 동기화·테스트 알림·점검 창 동작 후 즉시 재조회 */
(function () {
  const API = '../control';
  const POLL_INTERVAL_MILLISECONDS = 30000;
  const DEFAULT_MAINTENANCE_HOURS = 1;
  const INFRASTRUCTURE_LABEL = '인프라';
  const GLOBAL_SCOPE = 'global';
  const controlFormat = window.ControlFormat;

  let isLoadingOverview = false;
  let isRefreshQueued = false;  // 조회 중 동작이 끝나면 끝난 뒤 한 번 더 조회

  function findElement(id) { return document.getElementById(id); }

  /* ---------- 1. 조회 · 폴링 ---------- */
  // isAfterAction: 동작 직후 갱신 (조회 중이면 건너뛰지 않고 끝난 뒤 재조회)
  async function loadOverview(isAfterAction) {
    if (document.hidden) return;
    if (isLoadingOverview) {
      if (isAfterAction === true) isRefreshQueued = true;
      return;
    }
    isLoadingOverview = true;
    try {
      const response = await apiFetch(API + '/overview');
      if (!response.ok) throw new Error('overview status ' + response.status);
      render(await response.json());
    } catch (error) {
      console.warn('control overview failed:', error);
    } finally {
      isLoadingOverview = false;
      if (isRefreshQueued) {
        isRefreshQueued = false;
        loadOverview(true);
      }
    }
  }

  function render(overview) {
    renderRegistryError(overview.registry_error);
    renderSummary(overview.summary);
    renderHeartbeat(overview);
    renderIncidents(overview);
    renderServices(overview);
    renderEvents(overview);
    renderFormOptions(overview);
    lucide.createIcons();
  }

  /* ---------- 2. 렌더 ---------- */
  function renderRegistryError(errorText) {
    findElement('control-registry-error').hidden = !errorText;
    findElement('control-registry-error-text').textContent = errorText || '';
  }

  function renderSummary(summary) {
    findElement('control-count-ok').textContent = summary.ok;
    findElement('control-count-down').textContent = summary.down;
    findElement('control-count-maintenance').textContent = summary.maintenance;
    findElement('control-count-needs-attention').textContent = summary.needs_attention;
  }

  // 심박 is_ok: true 정상 / false 실패 / null 기록 없음
  function renderHeartbeat(overview) {
    const heartbeat = overview.heartbeat;
    const badge = findElement('control-heartbeat-badge');
    const stateClass = heartbeat.is_ok === null ? 'badge-ghost' : (heartbeat.is_ok ? 'badge-success' : 'badge-error');
    const stateText = heartbeat.is_ok === null ? '심박 기록 없음' : (heartbeat.is_ok ? '심박 정상' : '심박 실패');
    badge.className = 'badge gap-1 text-xs py-2 px-2.5 ' + stateClass;
    badge.textContent = stateText;
    findElement('control-heartbeat-detail').textContent = heartbeat.last_ok_at
      ? '마지막 성공 ' + controlFormat.formatDateTime(heartbeat.last_ok_at) + ' (' + controlFormat.formatElapsed(heartbeat.last_ok_at) + ')' : '';
    const onboarding = findElement('control-onboarding-badge');
    onboarding.className = 'badge badge-sm ' + (overview.onboarding.is_applied ? 'badge-success' : 'badge-ghost');
    onboarding.textContent = overview.onboarding.is_applied ? '디스코드 온보딩 적용됨' : '디스코드 온보딩 미적용';
    findElement('control-last-tick').textContent = overview.last_tick_at ? '마지막 점검 ' + controlFormat.formatElapsed(overview.last_tick_at) : '';
  }

  function serviceNameById(overview) {
    const names = {};
    overview.services.forEach(function (service) { names[service.id] = service.name; });
    return names;
  }

  function renderIncidents(overview) {
    const names = serviceNameById(overview);
    const openIncidents = overview.incidents.filter(function (incident) { return !incident.ended_at; });
    findElement('control-incident-count').textContent = openIncidents.length;
    const body = findElement('control-incident-body');
    body.replaceChildren();
    if (!openIncidents.length) { body.appendChild(controlFormat.createEmptyRow(4, '진행 중인 장애가 없습니다')); return; }
    openIncidents.forEach(function (incident) {
      const row = document.createElement('tr');
      row.appendChild(controlFormat.createCell(names[incident.service_id] || incident.service_id, 'font-semibold'));
      row.appendChild(controlFormat.createCell(controlFormat.describeCause(incident.cause)));
      row.appendChild(controlFormat.createCell(controlFormat.formatDateTime(incident.started_at)));
      row.appendChild(controlFormat.createCell(controlFormat.formatElapsed(incident.started_at)));
      body.appendChild(row);
    });
  }

  // 프로젝트 순서대로 묶고 인프라(project_id null)는 마지막
  function groupServicesByProject(overview) {
    const groups = overview.projects.map(function (project) {
      return { label: project.name, services: overview.services.filter(function (service) { return service.project_id === project.id; }) };
    });
    groups.push({ label: INFRASTRUCTURE_LABEL, services: overview.services.filter(function (service) { return service.project_id === null; }) });
    return groups.filter(function (group) { return group.services.length; });
  }

  function renderServices(overview) {
    const body = findElement('control-service-body');
    body.replaceChildren();
    const groups = groupServicesByProject(overview);
    if (!groups.length) { body.appendChild(controlFormat.createEmptyRow(6, '등록된 서비스가 없습니다')); return; }
    groups.forEach(function (group) {
      const headerRow = document.createElement('tr');
      const headerCell = controlFormat.createCell(group.label, 'font-bold bg-base-200');
      headerCell.colSpan = 6;
      headerRow.appendChild(headerCell);
      body.appendChild(headerRow);
      group.services.forEach(function (service) { body.appendChild(createServiceRow(service)); });
    });
  }

  function createServiceRow(service) {
    const row = document.createElement('tr');
    const nameCell = controlFormat.createCell(service.name, 'font-semibold');
    if (service.is_public) nameCell.appendChild(controlFormat.createElement('span', 'badge badge-ghost badge-xs ml-2', '공개'));
    if (service.url) nameCell.appendChild(createServiceLink(service.url));
    row.appendChild(nameCell);

    const statusCell = controlFormat.createCell(controlFormat.createStatusBadge(service));
    if (service.status === 'down' && service.cause) {
      statusCell.appendChild(controlFormat.createElement('div', 'text-xs opacity-60 mt-1', controlFormat.describeCause(service.cause)));
    }
    row.appendChild(statusCell);
    row.appendChild(controlFormat.createCell(controlFormat.describeCheck(service.internal), 'text-xs font-mono'));
    row.appendChild(controlFormat.createCell(controlFormat.describeCheck(service.external), 'text-xs font-mono'));
    const checkedAt = controlFormat.latestCheckedAt(service);
    row.appendChild(controlFormat.createCell(checkedAt ? controlFormat.formatElapsed(checkedAt) : '-', 'text-xs'));
    row.appendChild(createMaintenanceCell(service));
    return row;
  }

  /** 서비스 실제 주소 링크 (새 탭, 표시는 https:// 생략) */
  function createServiceLink(url) {
    const link = controlFormat.createElement('a', 'link link-hover block text-xs font-mono font-normal opacity-60', url.replace(/^https?:\/\//, ''));
    link.href = url;
    link.target = '_blank';
    link.rel = 'noopener noreferrer';
    return link;
  }

  function createMaintenanceCell(service) {
    const cell = document.createElement('td');
    if (!service.maintenance) { cell.textContent = '-'; return cell; }
    cell.appendChild(controlFormat.createElement('div', 'text-xs', controlFormat.formatDateTime(service.maintenance.until) + ' 까지'));
    if (service.maintenance.reason) cell.appendChild(controlFormat.createElement('div', 'text-xs opacity-60', service.maintenance.reason));
    // 등록 파일 창은 화면에서 해제할 수 없음 (파일에서 지워야 함)
    if (service.maintenance.source !== 'admin') {
      cell.appendChild(controlFormat.createElement('div', 'text-xs opacity-60', '등록 파일'));
      return cell;
    }
    const clearButton = controlFormat.createElement('button', 'btn btn-ghost btn-xs mt-1', '해제');
    clearButton.addEventListener('click', function () { clearMaintenance(service.id, clearButton); });
    cell.appendChild(clearButton);
    return cell;
  }

  function renderEvents(overview) {
    const body = findElement('control-event-body');
    body.replaceChildren();
    if (!overview.events.length) { body.appendChild(controlFormat.createEmptyRow(3, '접수된 이벤트가 없습니다')); return; }
    overview.events.forEach(function (event) {
      const row = document.createElement('tr');
      row.appendChild(controlFormat.createCell(controlFormat.formatDateTime(event.created_at)));
      row.appendChild(controlFormat.createCell(event.project_id));
      row.appendChild(controlFormat.createCell(controlFormat.createElement('span', 'badge badge-ghost badge-sm', event.kind)));
      body.appendChild(row);
    });
  }

  // 폴링마다 선택값 유지하며 옵션 갱신
  function renderFormOptions(overview) {
    fillSelect(findElement('control-maintenance-service'), overview.services.map(function (service) {
      return { value: service.id, label: service.name };
    }));
    fillSelect(findElement('control-test-alert-scope'), [{ value: GLOBAL_SCOPE, label: '전체 (관제-긴급)' }].concat(
      overview.projects.map(function (project) { return { value: project.id, label: project.name + ' (상태 채널)' }; })));
  }

  function fillSelect(select, options) {
    const selectedValue = select.value;
    select.replaceChildren();
    options.forEach(function (option) {
      const optionElement = controlFormat.createElement('option', '', option.label);
      optionElement.value = option.value;
      select.appendChild(optionElement);
    });
    if (selectedValue) select.value = selectedValue;
  }

  /* ---------- 3. 동작 ---------- */
  async function postJson(path, method, payload) {
    const response = await apiFetch(API + path, { method: method, body: payload ? JSON.stringify(payload) : undefined });
    let data = {};
    try { data = await response.json(); } catch (parseError) { /* 본문 없음 */ }
    return { ok: response.ok, status: response.status, data: data };
  }

  async function runWithButton(button, action) {
    button.disabled = true;
    try { await action(); } catch (error) { showToast('요청에 실패했습니다', 'error'); console.warn('control action failed:', error); }
    finally { button.disabled = false; }
  }

  async function syncDiscord() {
    const result = await postJson('/discord/sync', 'POST');
    const resultText = findElement('control-sync-result');
    resultText.hidden = false;
    if (result.status === 503 && result.data.error === 'discord_not_configured') {
      resultText.textContent = '디스코드 봇 토큰 또는 서버 ID가 설정되지 않았습니다';
      return;
    }
    if (!result.ok) { resultText.textContent = '동기화 실패 (' + (result.data.error || result.status) + ')'; return; }
    const report = result.data;
    resultText.textContent = '생성 ' + report.created + ' · 수정 ' + report.updated + ' · 보관 ' + report.archived
      + ' · 오류 ' + report.errors.length + ' · 온보딩 ' + (report.is_onboarding_applied ? '적용' : '미적용')
      + (report.errors.length ? ' · ' + report.errors[0] : '');
    loadOverview(true);
  }

  // 400 대상 오류 / 503 런타임 없음 / 그 외
  function describeTestAlertFailure(status) {
    if (status === 400) return '테스트 알림 대상이 올바르지 않습니다';
    if (status === 503) return '관제소를 사용할 수 없습니다';
    return '요청에 실패했습니다 (' + status + ')';
  }

  async function sendTestAlert() {
    const result = await postJson('/test-alert', 'POST', { scope: findElement('control-test-alert-scope').value });
    if (!result.ok) { showToast(describeTestAlertFailure(result.status), 'error'); return; }
    showToast(result.data.sent ? '테스트 알림을 보냈습니다' : '발송하지 못했습니다 (채널 연결 확인)', result.data.sent ? 'success' : 'warning');
  }

  async function setMaintenance(event) {
    event.preventDefault();
    const until = controlFormat.toIsoWithOffset(findElement('control-maintenance-until').value);
    if (!until) { showToast('종료 시각을 확인하세요', 'error'); return; }
    await runWithButton(findElement('control-maintenance-submit'), async function () {
      const result = await postJson('/maintenance', 'POST', {
        service_id: findElement('control-maintenance-service').value, until: until,
        reason: findElement('control-maintenance-reason').value.trim(),
      });
      if (!result.ok) {
        showToast(result.status === 404 ? '등록되지 않은 서비스입니다' : '입력값을 확인하세요 (종료 시각은 현재 이후 30일 이내)', 'error');
        return;
      }
      showToast('점검 중으로 설정했습니다', 'success');
      findElement('control-maintenance-reason').value = '';
      loadOverview(true);
    });
  }

  async function clearMaintenance(serviceId, button) {
    await runWithButton(button, async function () {
      const result = await postJson('/maintenance/' + encodeURIComponent(serviceId), 'DELETE');
      showToast(result.ok ? '점검 중을 해제했습니다' : '해제하지 못했습니다', result.ok ? 'success' : 'error');
      loadOverview(true);
    });
  }

  /* ---------- 4. 시작 ---------- */
  findElement('control-maintenance-until').value = controlFormat.localDateTimeAfterHours(DEFAULT_MAINTENANCE_HOURS);
  findElement('control-maintenance-form').addEventListener('submit', setMaintenance);
  findElement('control-discord-sync').addEventListener('click', function () { runWithButton(findElement('control-discord-sync'), syncDiscord); });
  findElement('control-test-alert').addEventListener('click', function () { runWithButton(findElement('control-test-alert'), sendTestAlert); });
  loadOverview();
  setInterval(loadOverview, POLL_INTERVAL_MILLISECONDS);
  // 탭 복귀 시 30초를 기다리지 않고 바로 갱신
  document.addEventListener('visibilitychange', function () { if (!document.hidden) loadOverview(); });
})();
