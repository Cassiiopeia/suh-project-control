/**
 * 공개 status HTML: 모델 > head(SEO) > 머리(로고·이름) > 전체 배너 > 공지·지연 안내 > 진행 중 장애 > 프로젝트 묶음(썸네일, 기본 펼침 details) > 범례 > 14일 장애 > 바닥
 * JS 없음 (접기는 details, 툴팁은 data-tip + CSS), 동적 문자열은 전부 escapeHtml
 */
import { escapeHtml } from './html_escape.js';
import { renderActiveIncidents, renderIncidentHistory, toMonthDayLabel } from './status_render_history.js';
import { renderSeoHead } from './status_seo.js';
import { STATUS_PAGE_CSS } from './status_style.js';
import { parseIsoMilliseconds, toKstDateTime } from './time.js';

export { escapeHtml } from './html_escape.js';
export { formatDurationLabel } from './status_render_history.js';

export const DELAYED_NOTICE_TEXT = '일부 서비스 상태 확인이 지연되고 있습니다';
export const POWERED_BY_TEXT = 'SUH 관제소';
// 좁은 화면에서 숨기는 오래된 막대 수 (90칸 중 앞 30칸 > 60일 표시)
const NARROW_HIDDEN_DAY_COUNT = 30;
// 이름 첫 글자 타일 색 개수 (status_style.js --color-tile-0 ~ 7)
const TILE_COLOR_COUNT = 8;

// 서비스 상태 > 표시 이름
const STATE_LABEL_BY_STATE = Object.freeze({
  up: '정상', degraded: '느림', down: '장애', maintenance: '점검 중', unknown: '확인 중',
});
// 전체 배너 아이콘 글자
const HERO_ICON_BY_STATE = Object.freeze({ up: '✓', degraded: '!', down: '!', maintenance: '…', unknown: '?' });
// 공지 수준 > 표시 이름
const NOTICE_LABEL_BY_LEVEL = Object.freeze({ info: '안내', warning: '주의', critical: '긴급' });
// 막대 범례 (색 등급 > 설명)
const LEGEND_ITEMS = Object.freeze([
  ['ok', '99.5% 이상'], ['warn', '95% 이상'], ['bad', '95% 미만'], ['none', '기록 없음'],
]);
const KNOWN_LEVELS = new Set(LEGEND_ITEMS.map(([level]) => level));

/** 모델 > HTML 문서 1장 */
export function renderStatusPage(model) {
  const groups = model.projects.map(renderProjectGroup).join('\n');
  return `<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="color-scheme" content="light dark">
${renderSeoHead(model)}
<style>${STATUS_PAGE_CSS}</style>
</head>
<body>
<main class="page">
${renderSiteHeader(model.page.title)}
${renderHero(model)}
${renderNotice(model.page.notice)}
${model.is_delayed ? renderDelayedNotice() : ''}
${renderActiveIncidents(model.incidents)}
${model.projects.length > 0 ? renderGroupSection(groups) : ''}
${renderIncidentHistory(model.incidents, model.generated_at)}
<footer class="footer"><span>${escapeHtml(model.page.title)}</span><span>Powered by <strong>${escapeHtml(POWERED_BY_TEXT)}</strong></span></footer>
</main>
</body>
</html>
`;
}

/** 머리: 로고 타일 + 사이트 이름 + 실시간 표시 */
function renderSiteHeader(title) {
  return `<header class="site-header"><a class="brand" href="/">`
    + `<img class="brand-logo" src="/logo.png" width="36" height="36" alt="">`
    + `<h1 class="brand-name">${escapeHtml(title)}</h1></a>`
    + `<span class="live-chip state-up"><span class="dot"></span>1분마다 확인</span></header>`;
}

/** 전체 상태 배너: 아이콘 + 문구 + 마지막 갱신 */
function renderHero(model) {
  const state = model.overall.state;
  return `<section class="hero state-${escapeHtml(state)}" role="status">`
    + `<span class="hero-icon" aria-hidden="true">${HERO_ICON_BY_STATE[state] ?? HERO_ICON_BY_STATE.unknown}</span>`
    + `<div><p class="hero-message">${escapeHtml(model.overall.message)}</p>`
    + `<p class="hero-detail">${escapeHtml(formatLastCheckedText(model.last_checked_at))}</p></div></section>`;
}

/** 공지 배너 (없으면 빈 문자열), 수준별 색 */
function renderNotice(notice) {
  if (!notice) return '';
  const level = NOTICE_LABEL_BY_LEVEL[notice.level] ? notice.level : 'info';
  return `<section class="notice notice-${level}" role="note"><span class="notice-label">${NOTICE_LABEL_BY_LEVEL[level]}</span>`
    + `<p class="notice-text">${escapeHtml(notice.text)}</p></section>`;
}

function renderDelayedNotice() {
  return `<section class="notice notice-delayed" role="note"><p class="notice-text">${escapeHtml(DELAYED_NOTICE_TEXT)}</p></section>`;
}

/** 묶음 목록 + 범례 */
function renderGroupSection(groups) {
  const legendItems = LEGEND_ITEMS.map(([level, label]) =>
    `<li><span class="legend-swatch ${level}"></span>${escapeHtml(label)}</li>`).join('');
  return `<h2 class="section-title">서비스 상태<small>최근 90일 가동률</small></h2>`
    + `<div class="groups">${groups}</div>`
    + `<ul class="legend" aria-label="막대 색 안내">${legendItems}</ul>`;
}

/** 프로젝트 묶음: 기본 펼침 details, summary(화살표·썸네일·이름·구성 요소 수·묶음 가동률·상태 점) > 서비스 행 */
function renderProjectGroup(project) {
  const stateLabel = STATE_LABEL_BY_STATE[project.state] ?? STATE_LABEL_BY_STATE.unknown;
  return `<details class="group" open><summary class="group-summary">`
    + `<span class="chevron" aria-hidden="true"></span>`
    + renderProjectThumbnail(project)
    + `<span class="group-title"><span class="group-name">${escapeHtml(project.name)}</span>`
    + `<span class="group-meta">구성 요소 ${project.service_count}개 · ${escapeHtml(stateLabel)}</span></span>`
    + `<span class="group-uptime">${escapeHtml(formatUptimeText(project.uptime_percent))}</span>`
    + `<span class="dot state-${escapeHtml(project.state)}" aria-label="${escapeHtml(stateLabel)}"></span>`
    + `</summary><div class="group-body">${project.services.map(renderServiceRow).join('')}</div></details>`;
}

/** 썸네일: 이미지 주소가 있으면 img, 없으면 이름 첫 글자 타일 (색은 프로젝트 id로 고정) */
function renderProjectThumbnail(project) {
  if (typeof project.icon_url === 'string' && project.icon_url.startsWith('/project-icons/')) {
    return `<img class="group-thumb" src="${escapeHtml(project.icon_url)}" width="40" height="40" loading="lazy" alt="">`;
  }
  const firstLetter = Array.from(String(project.name ?? '').trim())[0] ?? '?';
  return `<span class="group-thumb group-thumb-tile tile-${pickTileColorIndex(project.id)}" aria-hidden="true">${escapeHtml(firstLetter.toUpperCase())}</span>`;
}

/** 프로젝트 id > 타일 색 번호 0 ~ 7 (같은 id는 항상 같은 색) */
function pickTileColorIndex(projectId) {
  let hash = 0;
  for (const character of String(projectId ?? '')) hash = (hash * 31 + character.codePointAt(0)) % 100003;
  return hash % TILE_COLOR_COUNT;
}

/** 서비스 행: 이름·상태 > 90일 막대(툴팁) > 캡션(기간·가동률·오늘) */
function renderServiceRow(service) {
  const lastIndex = service.days.length - 1;
  const stateLabel = STATE_LABEL_BY_STATE[service.state] ?? STATE_LABEL_BY_STATE.unknown;
  let cells = '';
  service.days.forEach((day, index) => {
    const level = KNOWN_LEVELS.has(day.level) ? day.level : 'none';
    const olderClassName = index < NARROW_HIDDEN_DAY_COUNT ? ' older' : '';
    const dayLabel = index === lastIndex ? `오늘 · 현재 ${stateLabel}` : toMonthDayLabel(day.day);
    cells += `<span class="bar-cell ${level}${olderClassName}" data-tip="${dayLabel} · ${formatUptimeText(day.uptime_percent)}"></span>`;
  });
  return `<div class="service">`
    + `<div class="service-head"><span class="service-name">${escapeHtml(service.name)}</span>`
    + `<span class="pill state-${escapeHtml(service.state)}"><span class="dot"></span>${escapeHtml(stateLabel)}</span></div>`
    + `<div class="bars" role="img" aria-label="최근 가동 기록">${cells}</div>`
    + `<div class="bar-caption"><span><span class="caption-long">90일 전</span><span class="caption-short">60일 전</span></span>`
    + `<span>가동률 ${escapeHtml(formatUptimeText(service.uptime_percent))}</span><span>오늘</span></div>`
    + `</div>`;
}

/** 가동률 > '99.50%', 없으면 '기록 없음' */
function formatUptimeText(uptimePercent) {
  return typeof uptimePercent === 'number' ? `${uptimePercent.toFixed(2)}%` : '기록 없음';
}

/** 마지막 점검 시각 > '마지막 갱신 YYYY-MM-DD HH:MM KST', 없으면 '점검 기록 없음' */
function formatLastCheckedText(lastCheckedAt) {
  const milliseconds = parseIsoMilliseconds(lastCheckedAt);
  return milliseconds === null ? '점검 기록 없음' : `마지막 갱신 ${toKstDateTime(milliseconds)} KST`;
}
