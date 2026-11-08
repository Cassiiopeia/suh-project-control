import assert from 'node:assert/strict';
import { test } from 'node:test';

import { buildProjectIconUrl, sanitizeProjectIcons } from '../src/project_icons.js';
import { renderStatusPage } from '../src/status_page.js';
import { buildFixtureModel, createStatusConfig } from '../test_support/status_fixtures.js';

/** 프로젝트별 icon_version을 넣은 스냅샷 */
function configWithIconVersions(versionByProjectId) {
  const config = createStatusConfig();
  config.projects = config.projects.map((project) => ({ ...project, icon_version: versionByProjectId[project.id] ?? null }));
  return config;
}

test('모델: icon_version이 있으면 icon_url, 없거나 형식이 틀리면 null', () => {
  const model = buildFixtureModel({ config: configWithIconVersions({ elum: 'a1b2c3d4e5f6', suh: 'bad version!' }) });
  const urlByProjectId = Object.fromEntries(model.projects.map((project) => [project.id, project.icon_url]));
  assert.deepEqual(urlByProjectId, { elum: '/project-icons/elum.webp?v=a1b2c3d4e5f6', suh: null });
  assert.equal(buildProjectIconUrl({ id: 'Bad_ID', icon_version: 'abc' }), null);
  assert.equal(buildProjectIconUrl({ id: 'elum', icon_version: 12 }), null);
  assert.equal(buildProjectIconUrl({ id: 'elum' }), null);
});

test('모델(/api/status.json 본문): 옛 스냅샷은 icon_url null', () => {
  assert.ok(buildFixtureModel().projects.every((project) => project.icon_url === null));
});

test('렌더링: 이미지가 있으면 img(크기·lazy·alt 빈 값), 없으면 첫 글자 타일', () => {
  const html = renderStatusPage(buildFixtureModel({ config: configWithIconVersions({ elum: 'a1b2c3d4e5f6' }) }));
  assert.ok(html.includes('<img class="group-thumb" src="/project-icons/elum.webp?v=a1b2c3d4e5f6" width="40" height="40" loading="lazy" alt="">'));
  const tile = html.match(/<span class="group-thumb group-thumb-tile tile-([0-7])" aria-hidden="true">([^<]*)<\/span>/);
  assert.ok(tile, 'tile for project without icon');
  assert.equal(tile[2], 'S', 'first letter of SUH');
});

test('렌더링: 같은 프로젝트 id는 항상 같은 타일 색, 첫 글자는 이스케이프', () => {
  const config = createStatusConfig();
  config.projects[2] = { id: 'suh', name: '<b>"x"' };
  const firstHtml = renderStatusPage(buildFixtureModel({ config }));
  const secondHtml = renderStatusPage(buildFixtureModel({ config }));
  const colorOf = (html) => html.match(/group-thumb-tile (tile-[0-7])/g).join();
  assert.equal(colorOf(firstHtml), colorOf(secondHtml));
  assert.ok(firstHtml.includes('aria-hidden="true">&lt;</span>'));
  assert.equal(firstHtml.includes('<b>"x"'), false);
});

test('렌더링: 이름이 한글이면 첫 글자 그대로, 이름이 비면 물음표', () => {
  const config = createStatusConfig();
  config.projects[0] = { id: 'elum', name: '  이룸 (ELUM)' };
  config.projects[2] = { id: 'suh', name: '   ' };
  const html = renderStatusPage(buildFixtureModel({ config }));
  assert.ok(html.includes('aria-hidden="true">이</span>'));
  assert.ok(html.includes('aria-hidden="true">?</span>'));
});

test('렌더링: 공개 아이콘 경로가 아닌 icon_url(외부 주소 등)은 쓰지 않고 타일로 대체', () => {
  const model = buildFixtureModel();
  model.projects[0].icon_url = 'https://evil.example/x.png';
  model.projects[1].icon_url = '/project-icons/suh.webp?v=a"><script>1</script>';
  const html = renderStatusPage(model);
  assert.equal(html.includes('evil.example'), false);
  assert.equal(html.includes('<script>1</script>'), false);
});

test('아이콘 묶음 검증: 객체가 아니면 null, 유효한 것만 통과', () => {
  assert.equal(sanitizeProjectIcons(null), null);
  assert.equal(sanitizeProjectIcons([]), null);
  assert.equal(sanitizeProjectIcons('x'), null);
  const warn = console.warn;
  console.warn = () => {};
  try {
    assert.deepEqual(sanitizeProjectIcons({ elum: 'AAAA', 'Bad': 'AAAA' }), { elum: 'AAAA' });
  } finally {
    console.warn = warn;
  }
});
