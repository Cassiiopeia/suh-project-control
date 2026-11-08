/**
 * GET /project-icons/<id>.webp: meta project_icons_json 1키 조회 > 해당 id base64 디코드 > WebP 응답 (없음·손상 > 404)
 * 주소에 ?v=<icon_version>이 붙어 내용이 바뀌면 주소도 바뀌므로 1년 immutable 캐시
 */
import { PROJECT_ID_PATTERN } from './project_icons.js';
import { textResponse } from './http.js';
import { MetaKey, getMetaValues, parseJsonObject } from './store.js';

// 아이콘 경로 (id는 PROJECT_ID_PATTERN 규칙)
const PROJECT_ICON_PATH_PATTERN = /^\/project-icons\/([^/]+)\.webp$/;
// 응답 캐시 시간 (초, 1년)
const PROJECT_ICON_CACHE_SECONDS = 31536000;

/** 경로가 프로젝트 아이콘 경로인지 */
export function isProjectIconPath(pathname) {
  return PROJECT_ICON_PATH_PATTERN.test(pathname);
}

/** 아이콘 요청 > WebP 응답 (id 규칙 위반·아이콘 없음·base64 손상은 404) */
export async function handleProjectIconRequest(pathname, environment) {
  const projectId = PROJECT_ICON_PATH_PATTERN.exec(pathname)?.[1];
  if (projectId === undefined || !PROJECT_ID_PATTERN.test(projectId)) return textResponse('not found', 404);

  const meta = await getMetaValues(environment.DB, [MetaKey.PROJECT_ICONS_JSON]);
  const base64Text = parseJsonObject(meta[MetaKey.PROJECT_ICONS_JSON])?.[projectId];
  const iconBytes = typeof base64Text === 'string' ? decodeBase64OrNull(base64Text) : null;
  if (iconBytes === null) return textResponse('not found', 404);

  return new Response(iconBytes, {
    status: 200,
    headers: {
      'content-type': 'image/webp',
      'cache-control': `public, max-age=${PROJECT_ICON_CACHE_SECONDS}, immutable`,
      'x-content-type-options': 'nosniff',
    },
  });
}

/** base64 > Uint8Array (손상이면 null) */
function decodeBase64OrNull(base64Text) {
  try {
    const binaryText = atob(base64Text);
    const bytes = new Uint8Array(binaryText.length);
    for (let index = 0; index < binaryText.length; index += 1) bytes[index] = binaryText.charCodeAt(index);
    return bytes;
  } catch {
    return null;
  }
}
