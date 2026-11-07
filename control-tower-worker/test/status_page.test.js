import assert from 'node:assert/strict';
import { test } from 'node:test';

import { buildStatusModel, renderStatusPage, toUptimeLevel } from '../src/status_page.js';
import { formatDurationLabel } from '../src/status_render.js';
import {
  HIDDEN_STRINGS, STATUS_NOW_MILLISECONDS, TODAY_KST, createPublicIncidents, createRecentResults, createRollupRows,
  createStatusConfig, createTodayRollup, recentResult,
} from '../test_support/status_fixtures.js';

const MINUTE_MILLISECONDS = 60 * 1000;
const RECENT_HEARTBEAT_AT = new Date(STATUS_NOW_MILLISECONDS - MINUTE_MILLISECONDS).toISOString();
const INTERNAL_IPV4_PATTERN = /\b(?:10|127)\.\d{1,3}\.\d{1,3}\.\d{1,3}\b|192\.168\./;

/** 지정한 키만 덮어씀 (null도 그대로 전달) */
function buildFixtureModel(overrides = {}) {
  const pick = (key, createDefault) => (key in overrides ? overrides[key] : createDefault());
  return buildStatusModel(
    pick('config', createStatusConfig),
    pick('recentResults', createRecentResults),
    pick('todayRollup', createTodayRollup),
    pick('rollups', createRollupRows),
    pick('publicIncidents', createPublicIncidents),
    pick('lastHeartbeatAt', () => RECENT_HEARTBEAT_AT),
    pick('nowMilliseconds', () => STATUS_NOW_MILLISECONDS),
  );
}

/** 모델 서비스 1개 찾기 */
function findService(model, serviceId) {
  return model.projects.flatMap((project) => project.services).find((service) => service.id === serviceId);
}

/** 서비스 1개짜리 스냅샷으로 상태 계산 */
function stateOf(recent, { maintenance = [], failuresToDown = 3 } = {}) {
  const config = createStatusConfig();
  config.alert.failures_to_down = failuresToDown;
  config.maintenance = maintenance;
  const model = buildFixtureModel({ config, recentResults: { 'elum-api': recent } });
  return findService(model, 'elum-api').state;
}

test('비공개·paused 서비스와 내부 주소는 HTML·JSON 어디에도 없다', () => {
  const model = buildFixtureModel();
  const html = renderStatusPage(model);
  const json = JSON.stringify(model);
  for (const hidden of HIDDEN_STRINGS) {
    assert.equal(html.includes(hidden), false, `html leaks ${hidden}`);
    assert.equal(json.includes(hidden), false, `json leaks ${hidden}`);
  }
  assert.doesNotMatch(html, INTERNAL_IPV4_PATTERN);
  assert.doesNotMatch(json, INTERNAL_IPV4_PATTERN);
  assert.equal(json.includes('http'), false, 'json has no url');
});

test('공개 서비스만 프로젝트 이름순·서비스 이름순으로 묶고 빈 프로젝트는 뺀다', () => {
  const model = buildFixtureModel();
  assert.deepEqual(model.projects.map((project) => project.name), ['SUH', '이룸']);
  assert.deepEqual(model.projects[0].services.map((service) => service.id), ['suh-blog']);
  assert.deepEqual(model.projects[1].services.map((service) => service.name), ['이룸 API', '이룸 웹']);
});

test('상태 판정: 정상·느림·최근 1회 실패·연속 실패·데이터 없음', () => {
  assert.equal(stateOf([recentResult(true), recentResult(false), recentResult(false)]), 'up');
  assert.equal(stateOf([recentResult(true, true), recentResult(true), recentResult(true)]), 'degraded');
  assert.equal(stateOf([recentResult(false), recentResult(false), recentResult(true)]), 'degraded');
  assert.equal(stateOf([recentResult(false), recentResult(false), recentResult(false)]), 'down');
  assert.equal(stateOf([recentResult(false), recentResult(false)]), 'degraded', 'fewer than failures_to_down');
  assert.equal(stateOf([recentResult(false), recentResult(false)], { failuresToDown: 2 }), 'down');
  assert.equal(stateOf([]), 'unknown');
  assert.equal(findService(buildFixtureModel(), 'elum-web').state, 'unknown', 'no external check');
});

test('점검 창이 남아 있으면 maintenance, 끝났으면 원래 판정', () => {
  const failing = [recentResult(false), recentResult(false), recentResult(false)];
  const futureUntil = new Date(STATUS_NOW_MILLISECONDS + 30 * MINUTE_MILLISECONDS).toISOString();
  const pastUntil = new Date(STATUS_NOW_MILLISECONDS - MINUTE_MILLISECONDS).toISOString();
  assert.equal(stateOf(failing, { maintenance: [{ service_id: 'elum-api', until: futureUntil }] }), 'maintenance');
  assert.equal(stateOf(failing, { maintenance: [{ service_id: 'elum-api', until: pastUntil }] }), 'down');
  assert.equal(stateOf([], { maintenance: [{ service_id: 'elum-api', until: futureUntil }] }), 'maintenance');
});

test('전체 배너: 장애 > 느림 > 점검 > 정상 > 불러오는 중', () => {
  const failing = [recentResult(false), recentResult(false), recentResult(false)];
  const futureUntil = new Date(STATUS_NOW_MILLISECONDS + 30 * MINUTE_MILLISECONDS).toISOString();
  const maintenanceConfig = { ...createStatusConfig(), maintenance: [{ service_id: 'suh-blog', until: futureUntil }] };
  const cases = [
    [{ recentResults: { 'elum-api': failing, 'suh-blog': [recentResult(true, true)] } }, 'down', '일부 서비스에 장애가 있습니다'],
    [{ recentResults: { 'elum-api': [recentResult(true, true)] } }, 'degraded', '일부 서비스가 느리게 응답하고 있습니다'],
    [{ config: maintenanceConfig }, 'maintenance', '일부 서비스 점검 중입니다'],
    [{}, 'up', '모든 서비스가 정상 작동 중입니다'],
    [{ recentResults: {} }, 'unknown', '상태 정보를 불러오는 중입니다'],
    [{ config: null, recentResults: null, todayRollup: null, rollups: [], publicIncidents: null, lastHeartbeatAt: null },
      'unknown', '상태 정보를 불러오는 중입니다'],
  ];
  for (const [overrides, expectedState, expectedMessage] of cases) {
    const model = buildFixtureModel(overrides);
    assert.equal(model.overall.state, expectedState);
    assert.equal(model.overall.message, expectedMessage);
    assert.ok(renderStatusPage(model).includes(expectedMessage));
  }
});

test('지연 배너: 마지막 심박이 3분을 넘으면만 표시', () => {
  const delayedText = '일부 서비스 상태 확인이 지연되고 있습니다';
  const cases = [
    [new Date(STATUS_NOW_MILLISECONDS - 4 * MINUTE_MILLISECONDS).toISOString(), true],
    [new Date(STATUS_NOW_MILLISECONDS - 3 * MINUTE_MILLISECONDS).toISOString(), false],
    [RECENT_HEARTBEAT_AT, false],
    [null, false],
  ];
  for (const [lastHeartbeatAt, isDelayedExpected] of cases) {
    const model = buildFixtureModel({ lastHeartbeatAt });
    assert.equal(model.is_delayed, isDelayedExpected, String(lastHeartbeatAt));
    assert.equal(renderStatusPage(model).includes(delayedText), isDelayedExpected);
  }
});

test('막대 색 경계: 99.5% 이상 ok, 95% 이상 warn, 미만 bad, 없음 none', () => {
  assert.equal(toUptimeLevel(1000, 995), 'ok');
  assert.equal(toUptimeLevel(1000, 994), 'warn');
  assert.equal(toUptimeLevel(1000, 950), 'warn');
  assert.equal(toUptimeLevel(1000, 949), 'bad');
  assert.equal(toUptimeLevel(200, 199), 'ok', '99.5% exact');
  assert.equal(toUptimeLevel(20, 19), 'warn', '95% exact');
  assert.equal(toUptimeLevel(0, 0), 'none');
});

test('90일 막대: 오래된 날 > 오늘, 오늘은 today_rollup, 전날 미마감분도 반영', () => {
  const todayRollup = { day: '2026-11-06', services: { 'elum-api': [1000, 940] } };
  const model = buildFixtureModel({ todayRollup, rollups: [{ day: '2026-11-05', service_id: 'elum-api', total: 100, ok: 100 }] });
  const days = findService(model, 'elum-api').days;
  assert.equal(days.length, 90);
  assert.equal(days[0].day, '2026-08-10');
  assert.equal(days[89].day, TODAY_KST);
  assert.equal(days[89].level, 'none');
  assert.deepEqual(days[88], { day: '2026-11-06', uptime_percent: 94, level: 'bad' });
  assert.deepEqual(days[87], { day: '2026-11-05', uptime_percent: 100, level: 'ok' });
});

test('90일 가동률: 있는 날 합계 기준 소수 2자리, 데이터 없으면 null', () => {
  const rollups = [{ day: '2026-11-06', service_id: 'elum-api', total: 1000, ok: 990 }];
  const todayRollup = { day: TODAY_KST, services: { 'elum-api': [1000, 1000] } };
  const model = buildFixtureModel({ rollups, todayRollup });
  assert.equal(findService(model, 'elum-api').uptime_percent, 99.5);
  assert.equal(findService(model, 'elum-web').uptime_percent, null);
  const roundingModel = buildFixtureModel({ rollups: [], todayRollup: { day: TODAY_KST, services: { 'elum-api': [3, 2] } } });
  assert.equal(findService(roundingModel, 'elum-api').uptime_percent, 66.66);
  const html = renderStatusPage(model);
  assert.ok(html.includes('99.50%'));
});

test('최근 14일 장애: 공개 서비스만, 진행 중은 기간 무관, KST 시각·한국어 기간', () => {
  const publicIncidents = [
    ...createPublicIncidents(),
    { service_id: 'elum-api', started_at: '2026-10-01T00:00:00+00:00', ended_at: '2026-10-01T01:00:00+00:00' },
    { service_id: 'suh-blog', started_at: '2026-10-20T00:00:00+00:00', ended_at: null },
    { service_id: 'suh-blog', started_at: 'broken', ended_at: null },
  ];
  const model = buildFixtureModel({ publicIncidents });
  assert.deepEqual(model.incidents.map((incident) => [incident.service_id, incident.is_ongoing]),
    [['elum-api', false], ['suh-blog', true]]);
  assert.equal(model.incidents[0].duration_minutes, 72);
  assert.equal(model.incidents[0].project_name, '이룸');
  const html = renderStatusPage(model);
  assert.ok(html.includes('2026-11-06 14:00'));
  assert.ok(html.includes('2026-11-06 15:12'));
  assert.ok(html.includes('1시간 12분'));
  assert.ok(html.includes('진행 중'));
});

test('기간 표시: 분·시간·일', () => {
  assert.equal(formatDurationLabel(0), '1분 미만');
  assert.equal(formatDurationLabel(12), '12분');
  assert.equal(formatDurationLabel(60), '1시간');
  assert.equal(formatDurationLabel(72), '1시간 12분');
  assert.equal(formatDurationLabel(60 * 24 * 2 + 180), '2일 3시간');
});

test('등록 이름은 HTML 이스케이프', () => {
  const config = createStatusConfig();
  config.services[0].name = '<script>alert("x")</script>';
  config.projects[0].name = 'A & B';
  const html = renderStatusPage(buildFixtureModel({ config }));
  assert.equal(html.includes('<script>'), false);
  assert.ok(html.includes('&lt;script&gt;alert(&quot;x&quot;)&lt;/script&gt;'));
  assert.ok(html.includes('A &amp; B'));
});

test('HTML 골격: 제목·viewport·다크 모드·외부 자원 없음·360px 가로 스크롤 없음', () => {
  const html = renderStatusPage(buildFixtureModel());
  assert.ok(html.startsWith('<!doctype html>'));
  assert.ok(html.includes('<title>SUH 서비스 상태</title>'));
  assert.ok(html.includes('<meta name="viewport" content="width=device-width, initial-scale=1">'));
  assert.ok(html.includes(':root'));
  assert.ok(html.includes('@media (prefers-color-scheme: dark)'));
  assert.equal(/<script/i.test(html), false);
  assert.equal(/<link|<img|src=|url\(/i.test(html), false);
  for (const label of ['정상', '확인 중', '마지막 갱신']) assert.ok(html.includes(label), label);
  // 고정 폭(max-width 제외)은 360px 이하만
  const fixedWidths = [...html.matchAll(/(?<![-\w])width:\s*(\d+)px/g)].map((match) => Number(match[1]));
  assert.ok(fixedWidths.every((width) => width <= 360), `fixed widths ${fixedWidths}`);
  assert.ok(/min-width:\s*0/.test(html), 'bar cells shrink');
  assert.ok(html.includes('class="bar-cell ok"'));
});
