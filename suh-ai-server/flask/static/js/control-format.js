/* 관제소 화면 표시 도우미: 시각·경과·점검 결과 문구, 상태 배지, DOM 생성 (데이터는 textContent로만 삽입) */
(function () {
  const DATE_TIME_FORMAT = new Intl.DateTimeFormat('ko-KR', {
    timeZone: 'Asia/Seoul', month: '2-digit', day: '2-digit',
    hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false,
  });
  const SECONDS_PER_MINUTE = 60;
  const MINUTES_PER_HOUR = 60;
  const HOURS_PER_DAY = 24;

  // runtime 상태 + lifecycle + 점검 창 > 배지 문구와 색
  const STATUS_BADGES = {
    needs_attention: { label: '확인 필요', css: 'badge-warning' },
    maintenance: { label: '점검 중', css: 'badge-info' },
    down: { label: '장애', css: 'badge-error' },
    degraded: { label: '지연', css: 'badge-warning' },
    up: { label: '정상', css: 'badge-success' },
    unknown: { label: '대기', css: 'badge-ghost' },
  };
  // 장애 원인 코드 > 문구
  const CAUSE_LABELS = {
    service_down: '서비스 응답 없음',
    external_path: '외부 경로 장애',
    unreachable: '접근 불가',
  };

  function formatDateTime(isoText) {
    return isoText ? DATE_TIME_FORMAT.format(new Date(isoText)) : '-';
  }

  // "3분 전", "2시간 전"
  function formatElapsed(isoText) {
    if (!isoText) return '-';
    const elapsedSeconds = Math.max(0, Math.round((Date.now() - new Date(isoText).getTime()) / 1000));
    if (elapsedSeconds < SECONDS_PER_MINUTE) return elapsedSeconds + '초 전';
    const elapsedMinutes = Math.floor(elapsedSeconds / SECONDS_PER_MINUTE);
    if (elapsedMinutes < MINUTES_PER_HOUR) return elapsedMinutes + '분 전';
    const elapsedHours = Math.floor(elapsedMinutes / MINUTES_PER_HOUR);
    if (elapsedHours < HOURS_PER_DAY) return elapsedHours + '시간 전';
    return Math.floor(elapsedHours / HOURS_PER_DAY) + '일 전';
  }

  // 점검 결과 1건 > "정상 200 45ms" / "지연 200 6100ms" / "실패 timeout" / "-"
  function describeCheck(check) {
    if (!check) return '-';
    const statusText = check.status_code ? ' ' + check.status_code : '';
    if (!check.is_ok) return '실패 ' + (check.error || '') + statusText;
    return (check.is_slow ? '지연' : '정상') + statusText + ' ' + check.latency_milliseconds + 'ms';
  }

  function badgeKeyOf(service) {
    if (service.lifecycle === 'paused') return 'needs_attention';
    if (service.maintenance) return 'maintenance';
    return STATUS_BADGES[service.status] ? service.status : 'unknown';
  }

  function createStatusBadge(service) {
    const badge = STATUS_BADGES[badgeKeyOf(service)];
    return createElement('span', 'badge badge-sm ' + badge.css, badge.label);
  }

  function describeCause(cause) {
    return CAUSE_LABELS[cause] || cause || '-';
  }

  // 마지막 점검 시각: 내부·외부 중 더 늦은 것
  function latestCheckedAt(service) {
    const times = [service.internal, service.external]
      .filter(Boolean).map(function (check) { return check.checked_at; });
    return times.length ? times.sort().pop() : null;
  }

  function createElement(tagName, className, text) {
    const element = document.createElement(tagName);
    if (className) element.className = className;
    if (text !== undefined) element.textContent = text;
    return element;
  }

  function createCell(content, className) {
    const cell = createElement('td', className);
    if (content instanceof Node) cell.appendChild(content);
    else cell.textContent = content;
    return cell;
  }

  function createEmptyRow(columnCount, message) {
    const row = document.createElement('tr');
    const cell = createCell(message, 'opacity-60');
    cell.colSpan = columnCount;
    row.appendChild(cell);
    return row;
  }

  // datetime-local 값("2026-11-06T03:00", 브라우저 시간대) > "2026-11-06T03:00:00+09:00"
  function toIsoWithOffset(localDateTimeText) {
    const moment = new Date(localDateTimeText);
    if (isNaN(moment.getTime())) return null;
    const pad = function (number) { return String(Math.abs(number)).padStart(2, '0'); };
    const offsetMinutes = -moment.getTimezoneOffset();
    const offsetSign = offsetMinutes >= 0 ? '+' : '-';
    return moment.getFullYear() + '-' + pad(moment.getMonth() + 1) + '-' + pad(moment.getDate())
      + 'T' + pad(moment.getHours()) + ':' + pad(moment.getMinutes()) + ':' + pad(moment.getSeconds())
      + offsetSign + pad(Math.floor(Math.abs(offsetMinutes) / MINUTES_PER_HOUR)) + ':' + pad(Math.abs(offsetMinutes) % MINUTES_PER_HOUR);
  }

  // 현재 + N시간을 datetime-local 값으로
  function localDateTimeAfterHours(hours) {
    const moment = new Date(Date.now() + hours * MINUTES_PER_HOUR * SECONDS_PER_MINUTE * 1000);
    const shifted = new Date(moment.getTime() - moment.getTimezoneOffset() * SECONDS_PER_MINUTE * 1000);
    return shifted.toISOString().slice(0, 16);
  }

  window.ControlFormat = {
    formatDateTime, formatElapsed, describeCheck, createStatusBadge, describeCause, latestCheckedAt,
    createElement, createCell, createEmptyRow, toIsoWithOffset, localDateTimeAfterHours,
  };
})();
