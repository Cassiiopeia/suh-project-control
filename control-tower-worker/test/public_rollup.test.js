import assert from 'node:assert/strict';
import { beforeEach, test } from 'node:test';

import { buildPublicRollup, calculateFirstStatusDay, listStatusDays } from '../src/public_rollup.js';
import { runScheduled } from '../src/scheduled.js';
import { FakeD1Database } from '../test_support/fake_d1.js';
import { createEnvironment, createFakeFetch } from '../test_support/fakes.js';

const MINUTE_MILLISECONDS = 60 * 1000;
// 2026-11-04 KST 23:59 (= 14:59Z) > 다음 분이 KST 11-05
const BEFORE_KST_MIDNIGHT_MILLISECONDS = Date.UTC(2026, 10, 4, 14, 59);

const CONFIG = {
  alert: { failures_to_down: 3, slow_milliseconds: 5000 },
  projects: [{ id: 'elum', name: '이룸' }],
  services: [
    { id: 'public-api', name: 'API', project_id: 'elum', status: 'active', is_public: true,
      external: { url: 'https://public-api.example.com/', expect: [], timeout_seconds: 10 } },
    { id: 'private-admin', name: '관리', project_id: 'elum', status: 'active', is_public: false,
      external: { url: 'https://private-admin.example.com/', expect: [], timeout_seconds: 10 } },
    { id: 'paused-web', name: '웹', project_id: 'elum', status: 'paused', is_public: true,
      external: { url: 'https://paused-web.example.com/', expect: [], timeout_seconds: 10 } },
  ],
  maintenance: [],
};

let database;

beforeEach((context) => {
  database = new FakeD1Database();
  context.mock.method(console, 'log', () => {});
  context.mock.method(console, 'warn', () => {});
});

function insertRollupRow(day, serviceId, total, okCount) {
  database.prepare('INSERT INTO daily_rollup (day, service_id, total, ok) VALUES (?, ?, ?, ?)')
    .bind(day, serviceId, total, okCount).runSync();
}

/** daily_rollup을 읽은 SQL 수 세기 */
function countDailyRollupReads() {
  const executedSql = [];
  const originalPrepare = database.prepare.bind(database);
  database.prepare = (sql) => {
    executedSql.push(sql);
    return originalPrepare(sql);
  };
  return () => executedSql.filter((sql) => sql.startsWith('SELECT') && sql.includes('daily_rollup')).length;
}

test('막대 기간: 오늘 포함 90일, 첫 날짜 = 89일 전', () => {
  const nowMilliseconds = Date.UTC(2026, 10, 7, 3, 0);
  const days = listStatusDays(nowMilliseconds);
  assert.equal(days.length, 90);
  assert.equal(days[0], '2026-08-10');
  assert.equal(days[0], calculateFirstStatusDay(nowMilliseconds));
  assert.equal(days[89], '2026-11-07');
});

test('공개 집계: 공개·active만, 기간 안(오늘 제외), 마감분 덮어씀, 날짜 오름차순', () => {
  const rows = [
    { day: '2026-11-03', service_id: 'public-api', total: 10, ok: 9 },
    { day: '2026-08-09', service_id: 'public-api', total: 10, ok: 10 },
    { day: '2026-11-07', service_id: 'public-api', total: 10, ok: 10 },
    { day: '2026-11-01', service_id: 'public-api', total: 10, ok: 10 },
    { day: '2026-11-03', service_id: 'private-admin', total: 10, ok: 0 },
    { day: '2026-11-03', service_id: 'paused-web', total: 10, ok: 0 },
  ];
  const finishedRollup = { day: '2026-11-06', services: { 'public-api': [100, 99], 'private-admin': [100, 0] } };
  assert.deepEqual(buildPublicRollup(CONFIG, rows, finishedRollup, '2026-08-10', '2026-11-07'), {
    'public-api': [['2026-11-01', 10, 10], ['2026-11-03', 10, 9], ['2026-11-06', 100, 99]],
  });
  assert.deepEqual(buildPublicRollup(null, rows, null, '2026-08-10', '2026-11-07'), {});
});

test('크론: KST 날짜가 바뀌면 public_rollup_json을 daily_rollup 1회 읽어 다시 만든다', async () => {
  database.setMetaValue('config_json', JSON.stringify(CONFIG));
  insertRollupRow('2026-11-03', 'public-api', 1440, 1430);
  insertRollupRow('2026-11-03', 'private-admin', 1440, 0);
  const environment = createEnvironment(database);
  const fakeFetch = createFakeFetch(() => new Response('ok', { status: 200 }));

  // 첫 크론: 공개 집계가 없어 1회 생성
  await runScheduled(environment, BEFORE_KST_MIDNIGHT_MILLISECONDS - MINUTE_MILLISECONDS, fakeFetch);
  assert.deepEqual(JSON.parse(database.metaValue('public_rollup_json')), { 'public-api': [['2026-11-03', 1440, 1430]] });

  // 같은 날 다음 크론: 다시 읽지 않음
  const dailyRollupReadCount = countDailyRollupReads();
  await runScheduled(environment, BEFORE_KST_MIDNIGHT_MILLISECONDS, fakeFetch);
  assert.equal(dailyRollupReadCount(), 0);

  // 자정 넘김: 전날(11-04) 마감 > 1회 읽고 마감분 포함
  await runScheduled(environment, BEFORE_KST_MIDNIGHT_MILLISECONDS + MINUTE_MILLISECONDS, fakeFetch);
  assert.equal(dailyRollupReadCount(), 1);
  assert.deepEqual(JSON.parse(database.metaValue('public_rollup_json')), {
    'public-api': [['2026-11-03', 1440, 1430], ['2026-11-04', 2, 2]],
  });

  // 다음 분: 이미 마감 > 다시 읽지 않음
  await runScheduled(environment, BEFORE_KST_MIDNIGHT_MILLISECONDS + 2 * MINUTE_MILLISECONDS, fakeFetch);
  assert.equal(dailyRollupReadCount(), 1);
});
