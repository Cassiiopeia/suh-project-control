/**
 * 공개 정적 경로 7개: 아이콘(favicon.ico·favicon.png·apple-touch-icon·logo·og), robots.txt, sitemap.xml
 * 아이콘 base64는 모듈 로드 때 1회만 디코드 (요청마다 디코드 없음, 무료 CPU 한도), D1 읽기 없음
 */
import {
  APPLE_TOUCH_ICON_PNG_BASE64, FAVICON_ICO_BASE64, FAVICON_PNG_BASE64, LOGO_PNG_BASE64, OG_PNG_BASE64,
} from './brand_assets.js';
import { buildRobotsText, buildSitemapXml } from './status_seo.js';

// 정적 응답 캐시 시간 (초, 1일)
const SITE_ASSET_CACHE_SECONDS = 86400;
const PNG_CONTENT_TYPE = 'image/png';

// 경로 > {bytes, contentType} (모듈 범위 1회 디코드)
const BRAND_ASSET_BY_PATH = new Map([
  ['/favicon.ico', { bytes: decodeBase64(FAVICON_ICO_BASE64), contentType: 'image/x-icon' }],
  ['/favicon.png', { bytes: decodeBase64(FAVICON_PNG_BASE64), contentType: PNG_CONTENT_TYPE }],
  ['/apple-touch-icon.png', { bytes: decodeBase64(APPLE_TOUCH_ICON_PNG_BASE64), contentType: PNG_CONTENT_TYPE }],
  ['/logo.png', { bytes: decodeBase64(LOGO_PNG_BASE64), contentType: PNG_CONTENT_TYPE }],
  ['/og.png', { bytes: decodeBase64(OG_PNG_BASE64), contentType: PNG_CONTENT_TYPE }],
]);
// 경로 > 문서 생성 (robots 고정, sitemap은 오늘 날짜)
const TEXT_DOCUMENT_BY_PATH = new Map([
  ['/robots.txt', { build: () => buildRobotsText(), contentType: 'text/plain; charset=utf-8' }],
  ['/sitemap.xml', { build: (nowMilliseconds) => buildSitemapXml(nowMilliseconds), contentType: 'application/xml; charset=utf-8' }],
]);

export const SITE_ASSET_PATHS = new Set([...BRAND_ASSET_BY_PATH.keys(), ...TEXT_DOCUMENT_BY_PATH.keys()]);

/** 정적 경로 > 200 응답 (SITE_ASSET_PATHS 밖이면 null) */
export function handleSiteAssetRequest(pathname, nowMilliseconds) {
  const brandAsset = BRAND_ASSET_BY_PATH.get(pathname);
  if (brandAsset) return buildSiteAssetResponse(brandAsset.bytes, brandAsset.contentType);
  const textDocument = TEXT_DOCUMENT_BY_PATH.get(pathname);
  if (textDocument) return buildSiteAssetResponse(textDocument.build(nowMilliseconds), textDocument.contentType);
  return null;
}

function buildSiteAssetResponse(body, contentType) {
  return new Response(body, {
    status: 200,
    headers: {
      'content-type': contentType,
      'cache-control': `public, max-age=${SITE_ASSET_CACHE_SECONDS}`,
      'x-content-type-options': 'nosniff',
    },
  });
}

/** base64 > Uint8Array (atob: Workers·Node 공통) */
function decodeBase64(base64Text) {
  const binaryText = atob(base64Text);
  const bytes = new Uint8Array(binaryText.length);
  for (let index = 0; index < binaryText.length; index += 1) bytes[index] = binaryText.charCodeAt(index);
  return bytes;
}
