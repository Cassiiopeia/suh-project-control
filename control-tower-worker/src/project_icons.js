/**
 * 프로젝트 썸네일 공통: id 규칙, 심박으로 받은 아이콘 묶음 검증(규칙 밖 항목 제외), 공개 아이콘 주소 생성
 * 이미지 본문은 로그에 남기지 않음 (제외한 id 개수만 기록)
 */
import { isPlainObject } from './store.js';

// 프로젝트 id 규칙 (Flask override_validation과 같은 형식)
export const PROJECT_ID_PATTERN = /^[a-z0-9][a-z0-9-]{1,40}$/;
// 아이콘 1개 base64 최대 길이 (128px WebP 기준 여유, 글자 수)
export const MAXIMUM_ICON_BASE64_LENGTH = 40000;
// 한 번에 받는 아이콘 최대 개수
export const MAXIMUM_ICON_COUNT = 50;
// 아이콘 버전(이미지 해시 앞부분) 허용 형식
const ICON_VERSION_PATTERN = /^[A-Za-z0-9]{1,32}$/;
const BASE64_PATTERN = /^[A-Za-z0-9+/]+={0,2}$/;

/** 심박 project_icons > {id: base64} (객체 아님 > null, 규칙 밖·개수 초과 항목은 제외하고 경고 1줄) */
export function sanitizeProjectIcons(rawIcons) {
  if (!isPlainObject(rawIcons)) return null;
  const iconByProjectId = {};
  let rejectedCount = 0;
  for (const [projectId, base64Text] of Object.entries(rawIcons)) {
    const isAcceptable = Object.keys(iconByProjectId).length < MAXIMUM_ICON_COUNT
      && PROJECT_ID_PATTERN.test(projectId)
      && typeof base64Text === 'string'
      && base64Text.length <= MAXIMUM_ICON_BASE64_LENGTH
      && BASE64_PATTERN.test(base64Text);
    if (isAcceptable) iconByProjectId[projectId] = base64Text;
    else rejectedCount += 1;
  }
  if (rejectedCount > 0) console.warn(`[control-tower worker heartbeat] project icons rejected : ${rejectedCount}`);
  return iconByProjectId;
}

/** 프로젝트 > 공개 아이콘 주소 (버전·id 형식이 맞을 때만, 아니면 null) */
export function buildProjectIconUrl(project) {
  const iconVersion = project?.icon_version;
  if (typeof iconVersion !== 'string' || !ICON_VERSION_PATTERN.test(iconVersion)) return null;
  if (typeof project.id !== 'string' || !PROJECT_ID_PATTERN.test(project.id)) return null;
  return `/project-icons/${project.id}.webp?v=${iconVersion}`;
}
