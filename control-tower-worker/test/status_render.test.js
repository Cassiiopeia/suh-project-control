import assert from 'node:assert/strict';
import { test } from 'node:test';

import { renderStatusPage } from '../src/status_page.js';
import { readPageSettings } from '../src/status_page_settings.js';
import { buildJsonLd, buildPageDescription } from '../src/status_seo.js';
import {
  STATUS_NOW_MILLISECONDS, TODAY_KST, buildFixtureModel, createStatusConfig, recentResult,
} from '../test_support/status_fixtures.js';

/** page 설정을 넣은 스냅샷 */
function configWithPage(page) {
  return { ...createStatusConfig(), page };
}

/** JSON-LD 본문 추출 > 객체 */
function parseJsonLd(html) {
  const match = html.match(/<script type="application\/ld\+json">([\s\S]*?)<\/script>/);
  assert.ok(match, 'json-ld present');
  return JSON.parse(match[1]);
}

test('page 설정: 옛 스냅샷·잘못된 값은 기본 제목·공지 없음', () => {
  const defaults = { title: 'SUHSAECHAN Status', notice: null };
  assert.deepEqual(readPageSettings(null), defaults);
  assert.deepEqual(readPageSettings({}), defaults);
  assert.deepEqual(readPageSettings({ page: 'broken' }), defaults);
  assert.deepEqual(readPageSettings({ page: { title: '   ', notice: { text: '  ', level: 'info' } } }), defaults);
  assert.deepEqual(readPageSettings({ page: { title: 42, notice: { text: 7 } } }), defaults);
  assert.deepEqual(readPageSettings({ page: { title: ' 내 상태 ', notice: { text: '점검 예정', level: 'warning' } } }),
    { title: '내 상태', notice: { text: '점검 예정', level: 'warning' } });
  assert.equal(readPageSettings({ page: { notice: { text: '안내', level: 'loud' } } }).notice.level, 'info');
  assert.equal(readPageSettings({ page: { notice: { text: 'x'.repeat(400) } } }).notice.text.length, 300);
  assert.deepEqual(buildFixtureModel().page, defaults);
});

test('공지 배너: 수준별 클래스·라벨, 공지 없으면 배너 없음', () => {
  const cases = [['info', '안내'], ['warning', '주의'], ['critical', '긴급']];
  for (const [level, label] of cases) {
    const html = renderStatusPage(buildFixtureModel({ config: configWithPage({ notice: { text: '오늘 밤 점검', level } }) }));
    assert.ok(html.includes(`class="notice notice-${level}"`), level);
    assert.ok(html.includes(`<span class="notice-label">${label}</span>`), label);
    assert.ok(html.includes('오늘 밤 점검'));
  }
  assert.equal(renderStatusPage(buildFixtureModel()).includes('class="notice notice-'), false);
});

test('사이트 이름: 머리·title·og·JSON-LD·바닥에 반영', () => {
  const html = renderStatusPage(buildFixtureModel({ config: configWithPage({ title: 'Twin-Fang Status' }) }));
  assert.ok(html.includes('<title>Twin-Fang Status</title>'));
  assert.ok(html.includes('<h1 class="brand-name">Twin-Fang Status</h1>'));
  assert.ok(html.includes('<meta property="og:title" content="Twin-Fang Status">'));
  assert.ok(html.includes('<meta property="og:site_name" content="Twin-Fang Status">'));
  assert.equal(parseJsonLd(html)['@graph'][0].name, 'Twin-Fang Status');
  assert.ok(html.includes('Powered by <strong>SUH 관제소</strong>'));
});

test('제목·공지 XSS: 본문·속성 이스케이프, JSON-LD에서 </script> 탈출 불가', () => {
  const attack = '</script><script>alert("x")</script><img src=x onerror=1>';
  const html = renderStatusPage(buildFixtureModel({
    config: configWithPage({ title: attack, notice: { text: attack, level: 'critical' } }),
  }));
  assert.equal(html.includes('<script>alert'), false);
  assert.equal(html.includes('<img src=x'), false);
  assert.ok(html.includes('&lt;/script&gt;&lt;script&gt;alert(&quot;x&quot;)'));
  assert.equal([...html.matchAll(/<\/script>/g)].length, 1, 'only json-ld closes');
  assert.equal(parseJsonLd(html)['@graph'][0].name, attack, 'json-ld keeps original text');
  assert.equal(buildJsonLd('a<b>&c').includes('<'), false);
});

test('SEO 태그: 설명·대표 주소·OG·트위터·theme-color·아이콘·JSON-LD', () => {
  const html = renderStatusPage(buildFixtureModel());
  const description = 'SUHSAECHAN(Cassiiopeia) 서비스 실시간 상태와 90일 가동률 - 이룸, SUH 등';
  const expectedTags = [
    `<meta name="description" content="${description}">`,
    '<link rel="canonical" href="https://status.suhsaechan.kr/">',
    '<meta property="og:type" content="website">',
    '<meta property="og:url" content="https://status.suhsaechan.kr/">',
    `<meta property="og:description" content="${description}">`,
    '<meta property="og:image" content="https://status.suhsaechan.kr/og.png">',
    '<meta name="twitter:card" content="summary">',
    '<meta name="theme-color"',
    '<link rel="icon" href="/favicon.ico" sizes="any">',
    '<link rel="icon" type="image/png" href="/favicon.png">',
    '<link rel="apple-touch-icon" href="/apple-touch-icon.png">',
    '<img class="brand-logo" src="/logo.png"',
  ];
  for (const tag of expectedTags) assert.ok(html.includes(tag), tag);
  const [webSite, organization] = parseJsonLd(html)['@graph'];
  assert.equal(webSite['@type'], 'WebSite');
  assert.deepEqual(webSite.alternateName, ['Cassiiopeia Status', 'SUHSAECHAN Status']);
  assert.equal(webSite.url, 'https://status.suhsaechan.kr/');
  assert.deepEqual([organization['@type'], organization.name, organization.logo],
    ['Organization', 'SUHSAECHAN', 'https://status.suhsaechan.kr/logo.png']);
  assert.equal(buildPageDescription([]), 'SUHSAECHAN(Cassiiopeia) 서비스 실시간 상태와 90일 가동률');
  assert.ok(buildPageDescription(['a', 'b', 'c', 'd', 'e', 'f']).endsWith('- a, b, c, d, e 등'));
});

test('묶음 요약: 상태·구성 요소 수·90일 묶음 가동률(서비스 합계 기준)', () => {
  const failing = [recentResult(false), recentResult(false), recentResult(false)];
  const model = buildFixtureModel({
    recentResults: { 'elum-api': failing, 'suh-blog': [recentResult(true)] },
    publicRollup: { 'elum-api': [['2026-11-06', 1000, 900]] },
    todayRollup: { day: TODAY_KST, services: { 'elum-api': [1000, 1000], 'suh-blog': [10, 10] } },
  });
  const [elum, suh] = model.projects;
  assert.deepEqual([elum.state, elum.service_count, elum.uptime_percent], ['down', 2, 95]);
  assert.deepEqual([suh.state, suh.service_count, suh.uptime_percent], ['up', 1, 100]);
  assert.equal('totalCount' in elum.services[0], false, 'internal sums not exposed');
  const html = renderStatusPage(model);
  assert.ok(html.includes('구성 요소 2개 · 장애'));
  assert.ok(html.includes('<span class="group-uptime">95.00%</span>'));
  assert.equal([...html.matchAll(/<details class="group" open>/g)].length, 2, 'all groups open by default');
});

test('묶음 기본 펼침: 프로젝트가 많고 모두 정상이어도 전부 펼친다', () => {
  const config = createStatusConfig();
  for (const index of [1, 2, 3]) {
    config.projects.push({ id: `extra-${index}`, name: `추가 ${index}` });
    config.services.push({ id: `extra-service-${index}`, name: `추가 서비스 ${index}`, project_id: `extra-${index}`,
      status: 'active', is_public: true, external: null });
  }
  const recentResults = { 'elum-api': [recentResult(true)], 'elum-web': [recentResult(true)], 'suh-blog': [recentResult(true)] };
  for (const index of [1, 2, 3]) recentResults[`extra-service-${index}`] = [recentResult(true)];
  const html = renderStatusPage(buildFixtureModel({ config, recentResults }));
  assert.equal([...html.matchAll(/<details class="group"/g)].length, 5);
  assert.equal([...html.matchAll(/<details class="group" open>/g)].length, 5, 'every group open, still collapsible details');
});

test('막대 툴팁: data-tip에 날짜·가동률, 오늘은 현재 상태, 좁은 화면 숨김 30칸', () => {
  const model = buildFixtureModel({ publicRollup: { 'elum-api': [['2026-11-06', 1000, 995]] } });
  const html = renderStatusPage(model);
  assert.ok(html.includes('data-tip="11월 6일 · 99.50%"'));
  assert.ok(html.includes('data-tip="8월 10일 · 기록 없음"'));
  assert.ok(html.includes('data-tip="오늘 · 현재 정상 · 100.00%"'));
  assert.ok(html.includes('content: attr(data-tip)'));
  assert.ok(html.includes('::after'));
  const elumApiRow = html.slice(html.indexOf('이룸 API'), html.indexOf('이룸 웹'));
  assert.equal([...elumApiRow.matchAll(/class="bar-cell [a-z]+ older"/g)].length, 30);
  assert.equal([...elumApiRow.matchAll(/class="bar-cell /g)].length, 90);
});

test('진행 중 장애 카드 + 14일 날짜별 목록 (없는 날은 장애 없음)', () => {
  const publicIncidents = [
    { service_id: 'suh-blog', started_at: new Date(STATUS_NOW_MILLISECONDS - 40 * 60000).toISOString(), ended_at: null },
    { service_id: 'elum-api', started_at: '2026-11-06T05:00:00+00:00', ended_at: '2026-11-06T06:12:00+00:00' },
  ];
  const html = renderStatusPage(buildFixtureModel({ publicIncidents }));
  assert.ok(html.includes('진행 중인 장애 1건'));
  assert.ok(html.includes('SUH · SUH 블로그</span><span class="active-incident-time">2026-11-07 11:20 KST 시작 · 40분 경과'));
  assert.equal([...html.matchAll(/class="history-day"/g)].length, 14);
  assert.ok(html.includes('11월 7일 (토)'));
  assert.ok(html.includes('11월 6일 (금)'));
  assert.ok(html.includes('10월 25일 (일)'), 'oldest of 14 days');
  assert.equal([...html.matchAll(/<p class="history-empty">장애 없음<\/p>/g)].length, 12);
  assert.equal(renderStatusPage(buildFixtureModel({ publicIncidents: [] })).includes('진행 중인 장애'), false);
});
