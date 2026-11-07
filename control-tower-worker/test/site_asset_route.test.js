import assert from 'node:assert/strict';
import { test } from 'node:test';

import worker from '../src/index.js';
import { SITE_ASSET_PATHS, handleSiteAssetRequest } from '../src/site_asset_route.js';
import { FakeD1Database } from '../test_support/fake_d1.js';
import { createEnvironment } from '../test_support/fakes.js';

const ORIGIN = 'https://status.suhsaechan.kr';
const PNG_SIGNATURE = [0x89, 0x50, 0x4e, 0x47];
// 경로 > [content-type, 본문 앞 바이트 (PNG 서명 | ICO 헤더)]
const BINARY_EXPECTATIONS = Object.freeze({
  '/favicon.ico': ['image/x-icon', [0, 0, 1, 0]],
  '/favicon.png': ['image/png', PNG_SIGNATURE],
  '/apple-touch-icon.png': ['image/png', PNG_SIGNATURE],
  '/logo.png': ['image/png', PNG_SIGNATURE],
  '/og.png': ['image/png', PNG_SIGNATURE],
});

/** PNG IHDR 너비 (16~19바이트, 빅엔디언) */
function readPngWidth(bytes) {
  return new DataView(bytes.buffer, bytes.byteOffset).getUint32(16);
}

test('아이콘 5개: 200, content-type, 1일 캐시, nosniff, 형식 서명', async () => {
  const environment = createEnvironment(new FakeD1Database());
  for (const [path, [contentType, headerBytes]] of Object.entries(BINARY_EXPECTATIONS)) {
    const response = await worker.fetch(new Request(`${ORIGIN}${path}`), environment, {});
    assert.equal(response.status, 200, path);
    assert.equal(response.headers.get('content-type'), contentType, path);
    assert.equal(response.headers.get('cache-control'), 'public, max-age=86400', path);
    assert.equal(response.headers.get('x-content-type-options'), 'nosniff', path);
    const bytes = new Uint8Array(await response.arrayBuffer());
    assert.deepEqual([...bytes.slice(0, 4)], headerBytes, path);
  }
});

test('아이콘 크기: favicon 32, apple-touch 180, logo 128, og 512', async () => {
  const expectedWidthByPath = { '/favicon.png': 32, '/apple-touch-icon.png': 180, '/logo.png': 128, '/og.png': 512 };
  for (const [path, expectedWidth] of Object.entries(expectedWidthByPath)) {
    const bytes = new Uint8Array(await handleSiteAssetRequest(path, Date.now()).arrayBuffer());
    assert.equal(readPngWidth(bytes), expectedWidth, path);
  }
});

test('robots.txt: 전체 허용 + 사이트맵 주소', async () => {
  const response = await worker.fetch(new Request(`${ORIGIN}/robots.txt`), createEnvironment(new FakeD1Database()), {});
  assert.equal(response.status, 200);
  assert.equal(response.headers.get('content-type'), 'text/plain; charset=utf-8');
  assert.equal(response.headers.get('cache-control'), 'public, max-age=86400');
  assert.equal(await response.text(), 'User-agent: *\nAllow: /\nSitemap: https://status.suhsaechan.kr/sitemap.xml\n');
});

test('sitemap.xml: 루트 1개, lastmod = 오늘 KST', async () => {
  // 2026-11-06T16:00:00Z = KST 2026-11-07 01:00 (KST 날짜 기준 확인)
  const response = handleSiteAssetRequest('/sitemap.xml', Date.UTC(2026, 10, 6, 16, 0, 0));
  assert.equal(response.headers.get('content-type'), 'application/xml; charset=utf-8');
  const xml = await response.text();
  assert.ok(xml.startsWith('<?xml version="1.0" encoding="UTF-8"?>'));
  assert.equal([...xml.matchAll(/<loc>/g)].length, 1);
  assert.ok(xml.includes('<loc>https://status.suhsaechan.kr/</loc><lastmod>2026-11-07</lastmod>'));
});

test('정적 경로는 D1을 읽지 않고, 모르는 경로는 null·POST는 404', async () => {
  const database = new FakeD1Database();
  database.prepare = () => { throw new Error('db must not be read'); };
  for (const path of SITE_ASSET_PATHS) {
    const response = await worker.fetch(new Request(`${ORIGIN}${path}`), createEnvironment(database), {});
    assert.equal(response.status, 200, path);
  }
  assert.equal(handleSiteAssetRequest('/unknown.png', Date.now()), null);
  const postResponse = await worker.fetch(new Request(`${ORIGIN}/og.png`, { method: 'POST' }), createEnvironment(database), {});
  assert.equal(postResponse.status, 404);
});
