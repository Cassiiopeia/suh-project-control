import assert from 'node:assert/strict';
import { test } from 'node:test';

import worker from '../src/index.js';
import { handleStatusRequest } from '../src/status_route.js';
import { FakeD1Database } from '../test_support/fake_d1.js';
import { createEnvironment } from '../test_support/fakes.js';
import {
  HIDDEN_STRINGS, STATUS_NOW_MILLISECONDS, createPublicIncidents, createRecentResults, createRollupRows, createStatusConfig,
  createTodayRollup,
} from '../test_support/status_fixtures.js';

const ORIGIN = 'https://status.suhsaechan.kr';
const EXPECTED_CSP = "default-src 'none'; style-src 'unsafe-inline'; img-src data:; base-uri 'none'; frame-ancestors 'none'";

/** 공개·비공개 데이터가 든 D1 + 실행 SQL 기록 */
function createSeededDatabase() {
  const database = new FakeD1Database();
  database.setMetaValue('config_json', JSON.stringify(createStatusConfig()));
  database.setMetaValue('recent_results_json', JSON.stringify(createRecentResults()));
  database.setMetaValue('today_rollup_json', JSON.stringify(createTodayRollup()));
  database.setMetaValue('public_incidents_json', JSON.stringify(createPublicIncidents()));
  database.setMetaValue('last_heartbeat_at', new Date(STATUS_NOW_MILLISECONDS - 60000).toISOString());
  for (const row of [...createRollupRows(), { day: '2026-01-01', service_id: 'elum-api', total: 10, ok: 0 }]) {
    database.prepare('INSERT INTO daily_rollup (day, service_id, total, ok) VALUES (?, ?, ?, ?)')
      .bind(row.day, row.service_id, row.total, row.ok).runSync();
  }
  database.prepare('INSERT INTO check_run (checked_at, results_json) VALUES (?, ?)').bind('2026-11-07T03:00:00Z', '{}').runSync();
  const executedSql = [];
  const originalPrepare = database.prepare.bind(database);
  database.prepare = (sql) => {
    executedSql.push(sql);
    return originalPrepare(sql);
  };
  database.executedSql = executedSql;
  return database;
}

/** Cache API 가짜 (URL 키) */
function createFakeCache() {
  const responseByUrl = new Map();
  return {
    responseByUrl,
    async match(request) {
      return responseByUrl.get(request.url)?.clone();
    },
    async put(request, response) {
      responseByUrl.set(request.url, response);
    },
  };
}

test('GET / > 공개 HTML + 보안·캐시 헤더, 비공개 정보 없음', async () => {
  const database = createSeededDatabase();
  const response = await handleStatusRequest(new Request(`${ORIGIN}/`), createEnvironment(database), STATUS_NOW_MILLISECONDS, null);
  assert.equal(response.status, 200);
  assert.equal(response.headers.get('content-type'), 'text/html; charset=utf-8');
  assert.equal(response.headers.get('cache-control'), 'public, max-age=60');
  assert.equal(response.headers.get('x-content-type-options'), 'nosniff');
  assert.equal(response.headers.get('content-security-policy'), EXPECTED_CSP);
  const html = await response.text();
  assert.ok(html.includes('이룸 API'));
  for (const hidden of HIDDEN_STRINGS) assert.equal(html.includes(hidden), false, hidden);
});

test('GET /api/status.json > 같은 필터의 모델 JSON', async () => {
  const database = createSeededDatabase();
  const response = await handleStatusRequest(
    new Request(`${ORIGIN}/api/status.json`), createEnvironment(database), STATUS_NOW_MILLISECONDS, null,
  );
  assert.equal(response.status, 200);
  assert.equal(response.headers.get('content-type'), 'application/json; charset=utf-8');
  assert.equal(response.headers.get('content-security-policy'), EXPECTED_CSP);
  const text = await response.text();
  for (const hidden of HIDDEN_STRINGS) assert.equal(text.includes(hidden), false, hidden);
  const model = JSON.parse(text);
  assert.equal(model.overall.state, 'up');
  assert.deepEqual(model.projects.map((project) => project.name), ['SUH', '이룸']);
  const elumApi = model.projects[1].services[0];
  assert.equal(elumApi.days.length, 90);
  assert.equal(elumApi.days[88].uptime_percent, 100);
});

test('D1 읽기는 meta 1회 + daily_rollup 90일 1회, check_run은 훑지 않음', async () => {
  const database = createSeededDatabase();
  await handleStatusRequest(new Request(`${ORIGIN}/`), createEnvironment(database), STATUS_NOW_MILLISECONDS, null);
  assert.equal(database.executedSql.length, 2);
  assert.ok(database.executedSql.some((sql) => sql.includes('FROM meta')));
  assert.ok(database.executedSql.some((sql) => sql.includes('FROM daily_rollup')));
  assert.equal(database.executedSql.some((sql) => sql.includes('check_run')), false);
});

test('60초 캐시: 두 번째 요청은 D1 없이 캐시, 쿼리 문자열은 같은 키', async () => {
  const database = createSeededDatabase();
  const cache = createFakeCache();
  const environment = createEnvironment(database);
  const first = await handleStatusRequest(new Request(`${ORIGIN}/?a=1`), environment, STATUS_NOW_MILLISECONDS, cache);
  const firstHtml = await first.text();
  assert.deepEqual([...cache.responseByUrl.keys()], [`${ORIGIN}/`]);
  const queryCountAfterFirst = database.executedSql.length;
  const second = await handleStatusRequest(new Request(`${ORIGIN}/?b=2`), environment, STATUS_NOW_MILLISECONDS, cache);
  assert.equal(await second.text(), firstHtml);
  assert.equal(database.executedSql.length, queryCountAfterFirst);
});

test('설정이 아직 없으면 200 + 불러오는 중 배너', async () => {
  const response = await handleStatusRequest(
    new Request(`${ORIGIN}/`), createEnvironment(new FakeD1Database()), STATUS_NOW_MILLISECONDS, null,
  );
  assert.equal(response.status, 200);
  assert.ok((await response.text()).includes('상태 정보를 불러오는 중입니다'));
});

test('worker.fetch가 GET /, /api/status.json을 status 처리로 보낸다', async () => {
  const environment = createEnvironment(createSeededDatabase());
  const pageResponse = await worker.fetch(new Request(`${ORIGIN}/`), environment, { waitUntil() {} });
  assert.equal(pageResponse.status, 200);
  assert.ok((await pageResponse.text()).includes('<title>SUH 서비스 상태</title>'));
  const jsonResponse = await worker.fetch(new Request(`${ORIGIN}/api/status.json`), environment, { waitUntil() {} });
  assert.equal(jsonResponse.status, 200);
  assert.ok(Array.isArray((await jsonResponse.json()).projects));
});
