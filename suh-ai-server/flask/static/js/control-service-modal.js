/* 관제소 서비스 정보 창: GET /control/services/<id> > 기본 정보·점검 대상(내부 포함)·최근 점검·30일 가동률·최근 장애 10건
   window.ControlServiceModal.open(serviceId) 로 노출 (데이터는 textContent로만 삽입) */
(function () {
  const actions = window.ControlManageActions;
  const controlFormat = window.ControlFormat;
  const createElement = controlFormat.createElement;
  // 가동률 막대 색 기준 (%): 이상이면 초록, 그 아래 주황, 장애 많으면 빨강
  const UPTIME_GOOD_PERCENT = 99.5;
  const UPTIME_WARNING_PERCENT = 95;
  // 정보 창 라벨 열 폭
  const FIELD_LABEL_COLUMN_WIDTH = '7rem';
  const STATUS_LABELS = { active: '추적함', paused: '감시만', retired: '추적 안 함' };

  function findElement(id) { return document.getElementById(id); }

  async function open(serviceId) {
    const modal = findElement('control-service-modal');
    const body = findElement('control-service-modal-body');
    findElement('control-service-modal-title').textContent = serviceId;
    body.replaceChildren(createElement('div', 'opacity-60', '불러오는 중'));
    modal.showModal();
    try {
      const result = await actions.sendJson('GET', '/services/' + encodeURIComponent(serviceId));
      if (!result.ok) { body.replaceChildren(createElement('div', 'text-error', actions.describeFailure(result))); return; }
      render(result.data);
    } catch (error) {
      console.warn('control service detail failed:', error);
      body.replaceChildren(createElement('div', 'text-error', '정보를 불러오지 못했습니다'));
    }
  }

  function render(detail) {
    findElement('control-service-modal-title').textContent = detail.name + ' (' + detail.id + ')';
    findElement('control-service-modal-body').replaceChildren(
      createSection('기본 정보', createFieldList([
        ['출처', detail.source === 'custom' ? '화면 추가' : '등록 파일'],
        ['프로젝트', detail.project_id || '인프라'],
        ['추적', STATUS_LABELS[detail.status] || detail.status],
        ['공개', detail.is_listed_publicly ? '공개 중' : (detail.is_public ? '공개 설정 (숨김·추적 안 함으로 미공개)' : '비공개')],
        ['의존', detail.depends_on || '-'],
        ['덮어쓴 칸', detail.overridden_fields.length ? detail.overridden_fields.join(', ') : '없음'],
      ])),
      createSection('점검 대상', createFieldList([
        ['내부', describeCheckSpec(detail.checks.internal)],
        ['외부', describeCheckSpec(detail.checks.external)],
      ])),
      createSection('현재 상태', createFieldList([
        ['상태', detail.state.status + (detail.state.cause ? ' · ' + controlFormat.describeCause(detail.state.cause) : '')],
        ['시작', detail.state.since ? controlFormat.formatDateTime(detail.state.since) : '-'],
        ['최근 내부 점검', controlFormat.describeCheck(detail.last_checks.internal)],
        ['최근 외부 점검', controlFormat.describeCheck(detail.last_checks.external)],
      ])),
      createSection('최근 30일 가동률', createUptimeBars(detail.uptime_days)),
      createSection('최근 장애', createIncidentList(detail.incidents)));
  }

  function describeCheckSpec(check) {
    if (!check) return '없음';
    const expectText = check.expect.length ? ' · 기대 ' + check.expect.join(',') : '';
    return check.kind + ' ' + check.target + expectText + ' · ' + check.timeout_seconds + '초';
  }

  function createSection(title, content) {
    const section = createElement('section');
    section.appendChild(createElement('h4', 'font-semibold mb-1', title));
    section.appendChild(content);
    return section;
  }

  function createFieldList(fields) {
    const list = createElement('dl', 'grid gap-x-3 gap-y-1');
    // 미리 빌드된 app.css에 임의값 클래스가 없어 열 폭은 인라인 지정 (라벨 7rem | 값)
    list.style.gridTemplateColumns = FIELD_LABEL_COLUMN_WIDTH + ' 1fr';
    fields.forEach(function (field) {
      list.appendChild(createElement('dt', 'opacity-60', field[0]));
      list.appendChild(createElement('dd', 'break-all font-mono text-xs leading-5', field[1]));
    });
    return list;
  }

  // 일별 막대: 높이 고정, 색으로 가동률 구분, title로 날짜·수치
  function createUptimeBars(days) {
    if (!days.length) return createElement('p', 'opacity-60', '기록 없음');
    const bars = createElement('div', 'flex items-end gap-0.5 h-8');
    days.forEach(function (day) {
      const bar = createElement('div', 'flex-1 h-full rounded-sm ' + uptimeColorClass(day.percent));
      bar.title = day.day + ' · ' + (day.percent === null ? '데이터 없음' : day.percent + '%');
      bars.appendChild(bar);
    });
    const wrapper = createElement('div');
    wrapper.appendChild(bars);
    const totalTicks = days.reduce(function (sum, day) { return sum + day.total; }, 0);
    const okTicks = days.reduce(function (sum, day) { return sum + day.ok; }, 0);
    wrapper.appendChild(createElement('p', 'text-xs opacity-70 mt-1',
      totalTicks ? '평균 ' + (okTicks * 100 / totalTicks).toFixed(2) + '% (' + days.length + '일)' : '데이터 없음'));
    return wrapper;
  }

  function uptimeColorClass(percent) {
    if (percent === null) return 'bg-base-300';
    if (percent >= UPTIME_GOOD_PERCENT) return 'bg-success';
    return percent >= UPTIME_WARNING_PERCENT ? 'bg-warning' : 'bg-error';
  }

  function createIncidentList(incidents) {
    if (!incidents.length) return createElement('p', 'opacity-60', '장애 기록 없음');
    const list = createElement('ul', 'space-y-1');
    incidents.forEach(function (incident) {
      const endedText = incident.ended_at ? controlFormat.formatDateTime(incident.ended_at) : '진행 중';
      list.appendChild(createElement('li', 'text-xs',
        controlFormat.formatDateTime(incident.started_at) + ' ~ ' + endedText + ' · ' + controlFormat.describeCause(incident.cause)));
    });
    return list;
  }

  window.ControlServiceModal = { open: open };
})();
