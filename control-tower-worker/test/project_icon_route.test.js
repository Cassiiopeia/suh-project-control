import assert from 'node:assert/strict';
import { test } from 'node:test';

import worker from '../src/index.js';
import { FakeD1Database } from '../test_support/fake_d1.js';
import { createEnvironment } from '../test_support/fakes.js';

const ORIGIN = 'https://status.suhsaechan.kr';
// WebP 파일 머리 (RIFF....WEBP) 바이트
const ICON_BYTES = Uint8Array.from([0x52, 0x49, 0x46, 0x46, 0x04, 0x00, 0x00, 0x00, 0x57, 0x45, 0x42, 0x50]);

function createDatabaseWithIcons(icons) {
  const database = new FakeD1Database();
  database.setMetaValue('project_icons_json', JSON.stringify(icons));
  return database;
}

function requestIcon(database, path, method = 'GET') {
  return worker.fetch(new Request(`${ORIGIN}${path}`, { method }), createEnvironment(database), {});
}

test('아이콘 경로: 저장된 WebP를 1년 immutable 캐시로 응답한다 (?v= 무시)', async () => {
  const database = createDatabaseWithIcons({ elum: Buffer.from(ICON_BYTES).toString('base64') });
  const response = await requestIcon(database, '/project-icons/elum.webp?v=abc123');
  assert.equal(response.status, 200);
  assert.equal(response.headers.get('content-type'), 'image/webp');
  assert.equal(response.headers.get('cache-control'), 'public, max-age=31536000, immutable');
  assert.equal(response.headers.get('x-content-type-options'), 'nosniff');
  assert.deepEqual(new Uint8Array(await response.arrayBuffer()), ICON_BYTES);
});

test('아이콘 경로: 아이콘 없음·저장소 비어 있음·손상된 base64는 404', async () => {
  const withBrokenIcon = createDatabaseWithIcons({ elum: 'not*valid*base64' });
  assert.equal((await requestIcon(withBrokenIcon, '/project-icons/elum.webp')).status, 404, 'corrupted');
  assert.equal((await requestIcon(withBrokenIcon, '/project-icons/other.webp')).status, 404, 'unknown id');
  assert.equal((await requestIcon(new FakeD1Database(), '/project-icons/elum.webp')).status, 404, 'empty store');
  const withBrokenJson = new FakeD1Database();
  withBrokenJson.setMetaValue('project_icons_json', '{broken');
  assert.equal((await requestIcon(withBrokenJson, '/project-icons/elum.webp')).status, 404, 'broken json');
});

test('아이콘 경로: id 규칙을 어기면 저장소를 읽지 않고 404', async () => {
  const database = createDatabaseWithIcons({ 'Bad_ID': 'AAAA', 'a': 'AAAA' });
  let isDatabaseTouched = false;
  const originalPrepare = database.prepare.bind(database);
  database.prepare = (sql) => { isDatabaseTouched = true; return originalPrepare(sql); };
  for (const path of ['/project-icons/Bad_ID.webp', '/project-icons/a.webp', '/project-icons/..%2Fx.webp', '/project-icons/.webp']) {
    assert.equal((await requestIcon(database, path)).status, 404, path);
  }
  assert.equal(isDatabaseTouched, false);
});

test('아이콘 경로: GET만 허용, 확장자가 다르면 404', async () => {
  const database = createDatabaseWithIcons({ elum: 'AAAA' });
  assert.equal((await requestIcon(database, '/project-icons/elum.webp', 'POST')).status, 404);
  assert.equal((await requestIcon(database, '/project-icons/elum.png')).status, 404);
});
