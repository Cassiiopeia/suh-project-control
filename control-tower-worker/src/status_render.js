/**
 * 공개 status HTML: 모델 > 전체 배너·지연 안내 > 프로젝트 카드(서비스 행·90일 막대·가동률) > 범례 > 최근 14일 장애 > 마지막 갱신
 * 외부 자원·스크립트 없음, 동적 문자열은 전부 escapeHtml
 */
import { STATUS_PAGE_CSS } from './status_style.js';
import { parseIsoMilliseconds, toKstDateTime } from './time.js';

export const STATUS_PAGE_TITLE = 'SUH 서비스 상태';
export const DELAYED_NOTICE_TEXT = '일부 서비스 상태 확인이 지연되고 있습니다';
// 좁은 화면에서 숨기는 오래된 막대 수 (90칸 중 앞 30칸 > 60일 표시)
const NARROW_HIDDEN_DAY_COUNT = 30;

// 서비스 상태 > 표시 이름
const STATE_LABEL_BY_STATE = Object.freeze({
  up: '정상', degraded: '느림', down: '장애', maintenance: '점검 중', unknown: '확인 중',
});
// 막대 범례 (색 등급 > 설명)
const LEGEND_ITEMS = Object.freeze([
  ['ok', '99.5% 이상'], ['warn', '95% 이상'], ['bad', '95% 미만'], ['none', '기록 없음'],
]);
// 막대 칸 HTML (등급 > 고정 문자열, 칸마다 이스케이프·title 없이 CPU 절약), older = 좁은 화면에서 숨김
const BAR_CELL_HTML_BY_LEVEL = buildBarCellHtmlByLevel('');
const OLDER_BAR_CELL_HTML_BY_LEVEL = buildBarCellHtmlByLevel(' older');

function buildBarCellHtmlByLevel(extraClassName) {
  return Object.freeze(Object.fromEntries(
    LEGEND_ITEMS.map(([level]) => [level, `<span class="bar-cell ${level}${extraClassName}"></span>`]),
  ));
}
const HTML_ESCAPE_BY_CHARACTER = Object.freeze({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' });

/** 모델 > HTML 문서 1장 */
export function renderStatusPage(model) {
  const projectCards = model.projects.map(renderProjectCard).join('');
  return `<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="color-scheme" content="light dark">
<title>${escapeHtml(STATUS_PAGE_TITLE)}</title>
<style>${STATUS_PAGE_CSS}</style>
</head>
<body>
<main class="page">
<h1 class="page-title">${escapeHtml(STATUS_PAGE_TITLE)}</h1>
<section class="banner state-${escapeHtml(model.overall.state)}" role="status"><span class="dot"></span><span>${escapeHtml(model.overall.message)}</span></section>
${model.is_delayed ? `<p class="notice">${escapeHtml(DELAYED_NOTICE_TEXT)}</p>` : ''}
${projectCards}
${model.projects.length > 0 ? renderLegend() : ''}
${renderIncidentSection(model.incidents)}
<footer class="footer">${escapeHtml(formatLastCheckedText(model.last_checked_at))}</footer>
</main>
</body>
</html>
`;
}

/** 문자열 HTML 이스케이프 (& < > " ') */
export function escapeHtml(value) {
  return String(value ?? '').replace(/[&<>"']/g, (character) => HTML_ESCAPE_BY_CHARACTER[character]);
}

/** 분 > 한국어 기간 (예: 1시간 12분, 2일 3시간, 1분 미만) */
export function formatDurationLabel(totalMinutes) {
  const days = Math.floor(totalMinutes / (24 * 60));
  const hours = Math.floor((totalMinutes % (24 * 60)) / 60);
  const minutes = totalMinutes % 60;
  if (days > 0) return hours > 0 ? `${days}일 ${hours}시간` : `${days}일`;
  if (hours > 0) return minutes > 0 ? `${hours}시간 ${minutes}분` : `${hours}시간`;
  return minutes > 0 ? `${minutes}분` : '1분 미만';
}

function renderProjectCard(project) {
  return `<section class="card"><h2>${escapeHtml(project.name)}</h2>${project.services.map(renderServiceRow).join('')}</section>\n`;
}

/** 서비스 행: 이름·상태 > 90일 막대 > 캡션(기간·가동률·오늘) */
function renderServiceRow(service) {
  let cells = '';
  service.days.forEach((day, index) => {
    const cellHtmlByLevel = index < NARROW_HIDDEN_DAY_COUNT ? OLDER_BAR_CELL_HTML_BY_LEVEL : BAR_CELL_HTML_BY_LEVEL;
    cells += cellHtmlByLevel[day.level] ?? cellHtmlByLevel.none;
  });
  const uptimeText = service.uptime_percent === null ? '기록 없음' : `${service.uptime_percent.toFixed(2)}%`;
  return `<div class="service">`
    + `<div class="service-head"><span class="service-name">${escapeHtml(service.name)}</span>${renderStatePill(service.state)}</div>`
    + `<div class="bars" role="img" aria-label="최근 가동 기록">${cells}</div>`
    + `<div class="bar-caption"><span><span class="caption-long">90일 전</span><span class="caption-short">60일 전</span></span>`
    + `<span>가동률 ${escapeHtml(uptimeText)}</span><span>오늘</span></div>`
    + `</div>`;
}

function renderStatePill(state) {
  const label = STATE_LABEL_BY_STATE[state] ?? STATE_LABEL_BY_STATE.unknown;
  return `<span class="pill state-${escapeHtml(state)}"><span class="dot"></span>${escapeHtml(label)}</span>`;
}

function renderLegend() {
  const items = LEGEND_ITEMS.map(([level, label]) =>
    `<li><span class="legend-swatch ${level}"></span>${escapeHtml(label)}</li>`).join('');
  return `<ul class="legend" aria-label="막대 색 안내">${items}</ul>`;
}

/** 최근 14일 장애 카드 (없으면 안내 문구) */
function renderIncidentSection(incidents) {
  const body = incidents.length === 0
    ? '<p class="empty">최근 14일 동안 장애가 없었습니다</p>'
    : `<ul class="incidents">${incidents.map(renderIncident).join('')}</ul>`;
  return `<section class="card"><h2>최근 14일 장애</h2>${body}</section>`;
}

/** 장애 1건: 프로젝트·서비스 이름, 진행 중/해결됨, KST 시각·기간 (원인 없음) */
function renderIncident(incident) {
  const startedText = formatKstOrDash(incident.started_at);
  const durationText = formatDurationLabel(incident.duration_minutes);
  const timeText = incident.is_ongoing
    ? `${startedText} KST부터 · ${durationText} 경과`
    : `${startedText} ~ ${formatKstOrDash(incident.ended_at)} KST · ${durationText}`;
  const pill = incident.is_ongoing
    ? '<span class="pill state-down"><span class="dot"></span>진행 중</span>'
    : '<span class="pill state-up"><span class="dot"></span>해결됨</span>';
  return `<li class="incident"><div class="service-head">`
    + `<span class="service-name">${escapeHtml(incident.project_name)} · ${escapeHtml(incident.service_name)}</span>${pill}</div>`
    + `<p class="incident-time">${escapeHtml(timeText)}</p></li>`;
}

/** 마지막 점검 시각 > '마지막 갱신 YYYY-MM-DD HH:MM KST', 없으면 '점검 기록 없음' */
function formatLastCheckedText(lastCheckedAt) {
  const milliseconds = parseIsoMilliseconds(lastCheckedAt);
  return milliseconds === null ? '점검 기록 없음' : `마지막 갱신 ${toKstDateTime(milliseconds)} KST`;
}

/** ISO > KST 'YYYY-MM-DD HH:MM', 없거나 잘못되면 '-' */
function formatKstOrDash(isoText) {
  const milliseconds = parseIsoMilliseconds(isoText);
  return milliseconds === null ? '-' : toKstDateTime(milliseconds);
}
