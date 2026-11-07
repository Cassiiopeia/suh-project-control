import assert from 'node:assert/strict';
import { beforeEach, test } from 'node:test';

import worker from '../src/index.js';
import { handleStatusRequest } from '../src/status_route.js';
import { FakeD1Database } from '../test_support/fake_d1.js';
import { createEnvironment } from '../test_support/fakes.js';
import {
  HIDDEN_STRINGS, STATUS_NOW_MILLISECONDS, createPublicIncidents, createPublicRollup, createRecentResults, createStatusConfig,
  createTodayRollup,
} from '../test_support/status_fixtures.js';

const ORIGIN = 'https://status.suhsaechan.kr';
const EXPECTED_CSP = "default-src 'none'; style-src 'unsafe-inline'; img-src data:; base-uri 'none'; frame-ancestors 'none'";

beforeEach((context) => {
  context.mock.method(console, 'warn', () => {});
});

/** 공개·비공개 데이터가 든 D1 + 실행 SQL 기록 (daily_rollup·check_run에도 행을 넣어 읽지 않음 확인) */
function createSeededDatabase() {
  const database = new FakeD1Database();
  database.setMetaValue('config_json', JSON.stringify(createStatusConfig()));
  database.setMetaValue('recent_results_json', JSON.stringify(createRecentResults()));
  database.setMetaValue('today_rollup_json', JSON.stringify(createTodayRollup()));
  database.setMetaValue('public_rollup_json', JSON.stringify(createPublicRollup()));
  database.setMetaValue('public_incidents_json', JSON.stringify(createPublicIncidents()));
  database.setMetaValue('last_heartbeat_at', new Date(STATUS_NOW_MILLISECONDS - 60000).toISOString());
  for (const row of [{ day: '2026-11-05', service_id: 'elum-api', total: 10, ok: 0 }]) {
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

/** Cache API 가짜 (URL 키), isMatchFailing·isPutFailing이면 예외 */
function createFakeCache({ isMatchFailing = false, isPutFailing = false } = {}) {
  const responseByUrl = new Map();
  return {
    responseByUrl,
    async match(request) {
      if (isMatchFailing) throw new Error('cache read broken');
      return responseByUrl.get(request.url)?.clone();
    },
    put(request, response) {
      if (isPutFailing) throw new Error('cache write broken');
      responseByUrl.set(request.url, response);
      return Promise.resolve();
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
  assert.equal(elumApi.days[87].level, 'none', 'daily_rollup row ignored');
});

test('D1 읽기는 meta 1회뿐, daily_rollup·check_run은 읽지 않음', async () => {
  const database = createSeededDatabase();
  for (const path of ['/', '/api/status.json']) {
    database.executedSql.length = 0;
    await handleStatusRequest(new Request(`${ORIGIN}${path}`), createEnvironment(database), STATUS_NOW_MILLISECONDS, null);
    assert.equal(database.executedSql.length, 1, path);
    assert.ok(database.executedSql[0].includes('FROM meta'));
  }
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
  assert.equal(second.headers.get('content-security-policy'), EXPECTED_CSP);
  assert.equal(second.headers.get('x-content-type-options'), 'nosniff');
  assert.equal(second.headers.get('cache-control'), 'public, max-age=60');
});

test('캐시 읽기·쓰기 오류는 경고만 남기고 200 응답', async () => {
  const environment = createEnvironment(createSeededDatabase());
  for (const cache of [createFakeCache({ isPutFailing: true }), createFakeCache({ isMatchFailing: true })]) {
    const response = await handleStatusRequest(new Request(`${ORIGIN}/`), environment, STATUS_NOW_MILLISECONDS, cache);
    assert.equal(response.status, 200);
    assert.ok((await response.text()).includes('이룸 API'));
  }
  const pending = [];
  const response = await handleStatusRequest(new Request(`${ORIGIN}/`), environment, STATUS_NOW_MILLISECONDS,
    createFakeCache({ isPutFailing: true }), { waitUntil: (promise) => pending.push(promise) });
  assert.equal(response.status, 200);
  await Promise.all(pending);
  const warnings = console.warn.mock.calls.map((call) => String(call.arguments[0]));
  assert.ok(warnings.includes('[control-tower worker status] cache write failed : Error'));
  assert.ok(warnings.includes('[control-tower worker status] cache read failed : Error'));
});

test('손상된 config_json은 경고 후 불러오는 중 배너', async () => {
  const database = new FakeD1Database();
  database.setMetaValue('config_json', '{broken');
  const response = await handleStatusRequest(new Request(`${ORIGIN}/`), createEnvironment(database), STATUS_NOW_MILLISECONDS, null);
  assert.equal(response.status, 200);
  assert.ok((await response.text()).includes('상태 정보를 불러오는 중입니다'));
  assert.ok(console.warn.mock.calls.some((call) => call.arguments[0] === '[control-tower worker status] config_json invalid : ignored'));
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
