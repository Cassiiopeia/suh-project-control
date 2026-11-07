/* 관제소 관리자 페이지. base: /admin/control → API: ../control/*
   흐름: 진입 시 overview 조회 > 30초 폴링 > 표·요약 렌더 / 동기화·테스트 알림·점검 창 동작 후 즉시 재조회 */
(function () {
  const API = '../control';
  const POLL_INTERVAL_MILLISECONDS = 30000;
  const DEFAULT_MAINTENANCE_HOURS = 1;
  const INFRASTRUCTURE_LABEL = '인프라';
  const GLOBAL_SCOPE = 'global';
  const F = window.ControlFormat;

  let latestOverview = null;

  function el(id) { return document.getElementById(id); }

  /* ---------- 1. 조회 · 폴링 ---------- */
  async function loadOverview() {
    if (document.hidden) return;
    try {
      const resp = await apiFetch(API + '/overview');
      if (!resp.ok) throw new Error('overview status ' + resp.status);
      latestOverview = await resp.json();
      render(latestOverview);
    } catch (e) {
      console.warn('control overview failed:', e);
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
    el('control-registry-error').hidden = !errorText;
    el('control-registry-error-text').textContent = errorText || '';
  }

  function renderSummary(summary) {
    el('control-count-ok').textContent = summary.ok;
    el('control-count-down').textContent = summary.down;
    el('control-count-maintenance').textContent = summary.maintenance;
    el('control-count-needs-attention').textContent = summary.needs_attention;
  }

  // 심박 is_ok: true 정상 / false 실패 / null 기록 없음
  function renderHeartbeat(overview) {
    const heartbeat = overview.heartbeat;
    const badge = el('control-heartbeat-badge');
    const stateClass = heartbeat.is_ok === null ? 'badge-ghost' : (heartbeat.is_ok ? 'badge-success' : 'badge-error');
    const stateText = heartbeat.is_ok === null ? '심박 기록 없음' : (heartbeat.is_ok ? '심박 정상' : '심박 실패');
    badge.className = 'badge gap-1 text-xs py-2 px-2.5 ' + stateClass;
    badge.textContent = stateText;
    el('control-heartbeat-detail').textContent = heartbeat.last_ok_at
      ? '마지막 성공 ' + F.formatDateTime(heartbeat.last_ok_at) + ' (' + F.formatElapsed(heartbeat.last_ok_at) + ')' : '';
    const onboarding = el('control-onboarding-badge');
    onboarding.className = 'badge badge-sm ' + (overview.onboarding.is_applied ? 'badge-success' : 'badge-ghost');
    onboarding.textContent = overview.onboarding.is_applied ? '디스코드 온보딩 적용됨' : '디스코드 온보딩 미적용';
    el('control-last-tick').textContent = overview.last_tick_at ? '마지막 점검 ' + F.formatElapsed(overview.last_tick_at) : '';
  }

  function serviceNameById(overview) {
    const names = {};
    overview.services.forEach(function (service) { names[service.id] = service.name; });
    return names;
  }

  function renderIncidents(overview) {
    const names = serviceNameById(overview);
    const openIncidents = overview.incidents.filter(function (incident) { return !incident.ended_at; });
    el('control-incident-count').textContent = openIncidents.length;
    const body = el('control-incident-body');
    body.replaceChildren();
    if (!openIncidents.length) { body.appendChild(F.createEmptyRow(4, '진행 중인 장애가 없습니다')); return; }
    openIncidents.forEach(function (incident) {
      const row = document.createElement('tr');
      row.appendChild(F.createCell(names[incident.service_id] || incident.service_id, 'font-semibold'));
      row.appendChild(F.createCell(F.describeCause(incident.cause)));
      row.appendChild(F.createCell(F.formatDateTime(incident.started_at)));
      row.appendChild(F.createCell(F.formatElapsed(incident.started_at)));
      body.appendChild(row);
    });
  }

  // 프로젝트 순서대로 묶고 인프라(project_id null)는 마지막
  function groupServicesByProject(overview) {
    const groups = overview.projects.map(function (project) {
      return { label: project.name, services: overview.services.filter(function (s) { return s.project_id === project.id; }) };
    });
    groups.push({ label: INFRASTRUCTURE_LABEL, services: overview.services.filter(function (s) { return s.project_id === null; }) });
    return groups.filter(function (group) { return group.services.length; });
  }

  function renderServices(overview) {
    const body = el('control-service-body');
    body.replaceChildren();
    const groups = groupServicesByProject(overview);
    if (!groups.length) { body.appendChild(F.createEmptyRow(6, '등록된 서비스가 없습니다')); return; }
    groups.forEach(function (group) {
      const headerRow = document.createElement('tr');
      const headerCell = F.createCell(group.label, 'font-bold bg-base-200');
      headerCell.colSpan = 6;
      headerRow.appendChild(headerCell);
      body.appendChild(headerRow);
      group.services.forEach(function (service) { body.appendChild(createServiceRow(service)); });
    });
  }

  function createServiceRow(service) {
    const row = document.createElement('tr');
    const nameCell = F.createCell(service.name, 'font-semibold');
    if (service.is_public) nameCell.appendChild(F.createElement('span', 'badge badge-ghost badge-xs ml-2', '공개'));
    row.appendChild(nameCell);

    const statusCell = F.createCell(F.createStatusBadge(service));
    if (service.status === 'down' && service.cause) {
      statusCell.appendChild(F.createElement('div', 'text-xs opacity-60 mt-1', F.describeCause(service.cause)));
    }
    row.appendChild(statusCell);
    row.appendChild(F.createCell(F.describeCheck(service.internal), 'text-xs font-mono'));
    row.appendChild(F.createCell(F.describeCheck(service.external), 'text-xs font-mono'));
    const checkedAt = F.latestCheckedAt(service);
    row.appendChild(F.createCell(checkedAt ? F.formatElapsed(checkedAt) : '-', 'text-xs'));
    row.appendChild(createMaintenanceCell(service));
    return row;
  }

  function createMaintenanceCell(service) {
    const cell = document.createElement('td');
    if (!service.maintenance) { cell.textContent = '-'; return cell; }
    cell.appendChild(F.createElement('div', 'text-xs', F.formatDateTime(service.maintenance.until) + ' 까지'));
    if (service.maintenance.reason) cell.appendChild(F.createElement('div', 'text-xs opacity-60', service.maintenance.reason));
    const clearButton = F.createElement('button', 'btn btn-ghost btn-xs mt-1', '해제');
    clearButton.addEventListener('click', function () { clearMaintenance(service.id, clearButton); });
    cell.appendChild(clearButton);
    return cell;
  }

  function renderEvents(overview) {
    const body = el('control-event-body');
    body.replaceChildren();
    if (!overview.events.length) { body.appendChild(F.createEmptyRow(3, '접수된 이벤트가 없습니다')); return; }
    overview.events.forEach(function (event) {
      const row = document.createElement('tr');
      row.appendChild(F.createCell(F.formatDateTime(event.created_at)));
      row.appendChild(F.createCell(event.project_id));
      row.appendChild(F.createCell(F.createElement('span', 'badge badge-ghost badge-sm', event.kind)));
      body.appendChild(row);
    });
  }

  // 폴링마다 선택값 유지하며 옵션 갱신
  function renderFormOptions(overview) {
    fillSelect(el('control-maintenance-service'), overview.services.map(function (service) {
      return { value: service.id, label: service.name };
    }));
    fillSelect(el('control-test-alert-scope'), [{ value: GLOBAL_SCOPE, label: '전체 (관제-긴급)' }].concat(
      overview.projects.map(function (project) { return { value: project.id, label: project.name + ' (상태 채널)' }; })));
  }

  function fillSelect(select, options) {
    const selectedValue = select.value;
    select.replaceChildren();
    options.forEach(function (option) {
      const optionElement = F.createElement('option', '', option.label);
      optionElement.value = option.value;
      select.appendChild(optionElement);
    });
    if (selectedValue) select.value = selectedValue;
  }

  /* ---------- 3. 동작 ---------- */
  async function postJson(path, method, payload) {
    const resp = await apiFetch(API + path, { method: method, body: payload ? JSON.stringify(payload) : undefined });
    let data = {};
    try { data = await resp.json(); } catch (e) { /* 본문 없음 */ }
    return { ok: resp.ok, status: resp.status, data: data };
  }

  async function runWithButton(button, action) {
    button.disabled = true;
    try { await action(); } catch (e) { showToast('요청에 실패했습니다', 'error'); console.warn('control action failed:', e); }
    finally { button.disabled = false; }
  }

  async function syncDiscord() {
    const result = await postJson('/discord/sync', 'POST');
    const resultText = el('control-sync-result');
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
    loadOverview();
  }

  async function sendTestAlert() {
    const result = await postJson('/test-alert', 'POST', { scope: el('control-test-alert-scope').value });
    if (!result.ok) { showToast('테스트 알림 대상이 올바르지 않습니다', 'error'); return; }
    showToast(result.data.sent ? '테스트 알림을 보냈습니다' : '발송하지 못했습니다 (채널 연결 확인)', result.data.sent ? 'success' : 'warning');
  }

  async function setMaintenance(event) {
    event.preventDefault();
    const until = F.toIsoWithOffset(el('control-maintenance-until').value);
    if (!until) { showToast('종료 시각을 확인하세요', 'error'); return; }
    await runWithButton(el('control-maintenance-submit'), async function () {
      const result = await postJson('/maintenance', 'POST', {
        service_id: el('control-maintenance-service').value, until: until,
        reason: el('control-maintenance-reason').value.trim(),
      });
      if (!result.ok) {
        showToast(result.status === 404 ? '등록되지 않은 서비스입니다' : '입력값을 확인하세요 (종료 시각은 현재 이후)', 'error');
        return;
      }
      showToast('점검 중으로 설정했습니다', 'success');
      el('control-maintenance-reason').value = '';
      loadOverview();
    });
  }

  async function clearMaintenance(serviceId, button) {
    await runWithButton(button, async function () {
      const result = await postJson('/maintenance/' + encodeURIComponent(serviceId), 'DELETE');
      showToast(result.ok ? '점검 중을 해제했습니다' : '해제하지 못했습니다', result.ok ? 'success' : 'error');
      loadOverview();
    });
  }

  /* ---------- 4. 시작 ---------- */
  el('control-maintenance-until').value = F.localDateTimeAfterHours(DEFAULT_MAINTENANCE_HOURS);
  el('control-maintenance-form').addEventListener('submit', setMaintenance);
  el('control-discord-sync').addEventListener('click', function () { runWithButton(el('control-discord-sync'), syncDiscord); });
  el('control-test-alert').addEventListener('click', function () { runWithButton(el('control-test-alert'), sendTestAlert); });
  loadOverview();
  setInterval(loadOverview, POLL_INTERVAL_MILLISECONDS);
})();
