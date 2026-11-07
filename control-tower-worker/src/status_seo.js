/**
 * 공개 페이지 SEO: head 메타(설명·대표 주소·OG·트위터·theme-color·아이콘) + JSON-LD, robots.txt, sitemap.xml
 * 설명은 공개 프로젝트 이름으로 생성, 동적 문자열은 escapeHtml·JSON-LD는 < 이스케이프
 */
import { escapeHtml } from './html_escape.js';
import { DEFAULT_SITE_TITLE } from './status_page_settings.js';
import { PAGE_BACKGROUND_COLOR_DARK, PAGE_BACKGROUND_COLOR_LIGHT } from './status_style.js';
import { toKstDay } from './time.js';

// 공개 주소 (대표 주소·OG·사이트맵 기준, wrangler.toml routes와 같음)
export const SITE_ORIGIN = 'https://status.suhsaechan.kr';
export const SITE_URL = `${SITE_ORIGIN}/`;
const ORGANIZATION_NAME = 'SUHSAECHAN';
// JSON-LD alternateName (소유자 확정 별칭)
const SITE_ALTERNATE_NAMES = Object.freeze(['Cassiiopeia Status', DEFAULT_SITE_TITLE]);
const DESCRIPTION_PREFIX = 'SUHSAECHAN(Cassiiopeia) 서비스 실시간 상태와 90일 가동률';
// 설명에 넣는 프로젝트 이름 최대 수
const MAXIMUM_DESCRIPTION_PROJECT_COUNT = 5;

/** 공개 프로젝트 이름 > 검색 설명 (예: ... 90일 가동률 - elum, romrom, passql 등) */
export function buildPageDescription(projectNames) {
  const names = projectNames.filter((name) => typeof name === 'string' && name !== '').slice(0, MAXIMUM_DESCRIPTION_PROJECT_COUNT);
  return names.length === 0 ? DESCRIPTION_PREFIX : `${DESCRIPTION_PREFIX} - ${names.join(', ')} 등`;
}

/** 모델 > head 안 SEO 태그 묶음 (title 포함) */
export function renderSeoHead(model) {
  const title = escapeHtml(model.page.title);
  const description = escapeHtml(buildPageDescription(model.projects.map((project) => project.name)));
  return `<title>${title}</title>
<meta name="description" content="${description}">
<link rel="canonical" href="${SITE_URL}">
<meta property="og:type" content="website">
<meta property="og:url" content="${SITE_URL}">
<meta property="og:title" content="${title}">
<meta property="og:description" content="${description}">
<meta property="og:site_name" content="${title}">
<meta property="og:image" content="${SITE_ORIGIN}/og.png">
<meta property="og:locale" content="ko_KR">
<meta name="twitter:card" content="summary">
<meta name="twitter:title" content="${title}">
<meta name="twitter:description" content="${description}">
<meta name="twitter:image" content="${SITE_ORIGIN}/og.png">
<meta name="theme-color" content="${PAGE_BACKGROUND_COLOR_LIGHT}" media="(prefers-color-scheme: light)">
<meta name="theme-color" content="${PAGE_BACKGROUND_COLOR_DARK}" media="(prefers-color-scheme: dark)">
<link rel="icon" href="/favicon.ico" sizes="any">
<link rel="icon" type="image/png" href="/favicon.png">
<link rel="apple-touch-icon" href="/apple-touch-icon.png">
<script type="application/ld+json">${buildJsonLd(model.page.title)}</script>`;
}

/** WebSite + Organization JSON-LD (< > & 는 \\u 이스케이프 > </script> 탈출 차단) */
export function buildJsonLd(title) {
  const graph = {
    '@context': 'https://schema.org',
    '@graph': [
      { '@type': 'WebSite', name: title, alternateName: SITE_ALTERNATE_NAMES, url: SITE_URL },
      { '@type': 'Organization', name: ORGANIZATION_NAME, url: SITE_URL, logo: `${SITE_ORIGIN}/logo.png` },
    ],
  };
  return JSON.stringify(graph).replace(/[<>&]/g, (character) => `\\u${character.charCodeAt(0).toString(16).padStart(4, '0')}`);
}

/** robots.txt: 전체 허용 + 사이트맵 */
export function buildRobotsText() {
  return `User-agent: *\nAllow: /\nSitemap: ${SITE_ORIGIN}/sitemap.xml\n`;
}

/** sitemap.xml: 루트 1개, lastmod = 오늘 (KST) */
export function buildSitemapXml(nowMilliseconds) {
  return '<?xml version="1.0" encoding="UTF-8"?>\n'
    + '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
    + `<url><loc>${SITE_URL}</loc><lastmod>${toKstDay(nowMilliseconds)}</lastmod><changefreq>always</changefreq></url>\n`
    + '</urlset>\n';
}
