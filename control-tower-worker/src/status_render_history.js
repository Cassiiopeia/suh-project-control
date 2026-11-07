/**
 * 공개 status HTML (장애): 진행 중 장애 카드, 최근 14일 날짜별 장애 목록, 기간·날짜 표시 변환
 * 원인은 모델에 없음 (서비스·프로젝트 이름, 시각, 기간만)
 */
import { escapeHtml } from './html_escape.js';
import { parseIsoMilliseconds, toKstDateTime, toKstDay } from './time.js';

// 날짜별 목록 일 수 (오늘 포함)
const HISTORY_DAY_COUNT = 14;
const MILLISECONDS_PER_DAY = 24 * 60 * 60 * 1000;
// 요일 표시 (일요일 0)
const WEEKDAY_LABELS = Object.freeze(['일', '월', '화', '수', '목', '금', '토']);

/** 분 > 한국어 기간 (예: 1시간 12분, 2일 3시간, 1분 미만) */
export function formatDurationLabel(totalMinutes) {
  const days = Math.floor(totalMinutes / (24 * 60));
  const hours = Math.floor((totalMinutes % (24 * 60)) / 60);
  const minutes = totalMinutes % 60;
  if (days > 0) return hours > 0 ? `${days}일 ${hours}시간` : `${days}일`;
  if (hours > 0) return minutes > 0 ? `${hours}시간 ${minutes}분` : `${hours}시간`;
  return minutes > 0 ? `${minutes}분` : '1분 미만';
}

/** KST 날짜(YYYY-MM-DD) > '11월 7일' */
export function toMonthDayLabel(day) {
  return `${Number(day.slice(5, 7))}월 ${Number(day.slice(8, 10))}일`;
}

/** 진행 중 장애 카드 (없으면 빈 문자열) */
export function renderActiveIncidents(incidents) {
  const ongoingIncidents = incidents.filter((incident) => incident.is_ongoing);
  if (ongoingIncidents.length === 0) return '';
  const items = ongoingIncidents.map((incident) => `<li class="active-incident">`
    + `<span class="active-incident-name">${escapeHtml(incident.project_name)} · ${escapeHtml(incident.service_name)}</span>`
    + `<span class="active-incident-time">${escapeHtml(formatKstOrDash(incident.started_at))} KST 시작 · `
    + `${escapeHtml(formatDurationLabel(incident.duration_minutes))} 경과</span></li>`).join('');
  return `<section class="active-incidents" aria-label="진행 중인 장애"><h2>진행 중인 장애 ${ongoingIncidents.length}건</h2>`
    + `<ul class="active-incident-list">${items}</ul></section>`;
}

/** 최근 14일 날짜별 장애 (오늘부터 과거순, 없는 날은 장애 없음) */
export function renderIncidentHistory(incidents, generatedAt) {
  const incidentsByDay = groupIncidentsByStartDay(incidents);
  const nowMilliseconds = parseIsoMilliseconds(generatedAt) ?? Date.now();
  let dayBlocks = '';
  for (let dayOffset = 0; dayOffset < HISTORY_DAY_COUNT; dayOffset += 1) {
    const day = toKstDay(nowMilliseconds - dayOffset * MILLISECONDS_PER_DAY);
    const dayIncidents = incidentsByDay.get(day) ?? [];
    const body = dayIncidents.length === 0
      ? '<p class="history-empty">장애 없음</p>'
      : `<ul class="incidents">${dayIncidents.map(renderHistoryIncident).join('')}</ul>`;
    dayBlocks += `<div class="history-day"><h3 class="history-date">${formatDayHeading(day)}</h3>${body}</div>`;
  }
  return `<h2 class="section-title">최근 14일 장애 기록</h2><section class="history">${dayBlocks}</section>`;
}

/** 장애 > Map(시작 KST 날짜 > [장애]) (모델이 최신 시작순이라 날짜 안도 최신순) */
function groupIncidentsByStartDay(incidents) {
  const incidentsByDay = new Map();
  for (const incident of incidents) {
    const startedMilliseconds = parseIsoMilliseconds(incident.started_at);
    if (startedMilliseconds === null) continue;
    const day = toKstDay(startedMilliseconds);
    const dayIncidents = incidentsByDay.get(day) ?? [];
    dayIncidents.push(incident);
    incidentsByDay.set(day, dayIncidents);
  }
  return incidentsByDay;
}

/** 장애 1건: 이름, 진행 중/해결됨, KST 시각·기간 */
function renderHistoryIncident(incident) {
  const startedText = formatKstOrDash(incident.started_at);
  const durationText = formatDurationLabel(incident.duration_minutes);
  const timeText = incident.is_ongoing
    ? `${startedText} KST부터 · ${durationText} 경과`
    : `${startedText} ~ ${formatKstOrDash(incident.ended_at)} KST · ${durationText}`;
  const pill = incident.is_ongoing
    ? '<span class="pill state-down"><span class="dot"></span>진행 중</span>'
    : '<span class="pill state-up"><span class="dot"></span>해결됨</span>';
  return `<li class="incident ${incident.is_ongoing ? 'state-down' : 'state-up'}"><div class="incident-head">`
    + `<span class="incident-name">${escapeHtml(incident.project_name)} · ${escapeHtml(incident.service_name)}</span>${pill}</div>`
    + `<p class="incident-time">${escapeHtml(timeText)}</p></li>`;
}

/** KST 날짜 > '11월 7일 (토)' */
function formatDayHeading(day) {
  const weekdayIndex = new Date(Date.UTC(Number(day.slice(0, 4)), Number(day.slice(5, 7)) - 1, Number(day.slice(8, 10)))).getUTCDay();
  return `${toMonthDayLabel(day)} (${WEEKDAY_LABELS[weekdayIndex]})`;
}

/** ISO > KST 'YYYY-MM-DD HH:MM', 없거나 잘못되면 '-' */
function formatKstOrDash(isoText) {
  const milliseconds = parseIsoMilliseconds(isoText);
  return milliseconds === null ? '-' : toKstDateTime(milliseconds);
}
