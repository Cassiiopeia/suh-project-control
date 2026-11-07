/**
 * 공개 페이지 설정 (순수 함수): 스냅샷 page > {title, notice|null}
 * page 없는 옛 스냅샷·잘못된 값은 기본값 (제목 SUHSAECHAN Status, 공지 없음)
 */
import { isPlainObject } from './store.js';

export const DEFAULT_SITE_TITLE = 'SUHSAECHAN Status';
// 공지 수준: info 안내, warning 주의, critical 긴급
export const NoticeLevel = Object.freeze({ INFO: 'info', WARNING: 'warning', CRITICAL: 'critical' });

// 제목 최대 글자 수 (Flask 검증 60자, Worker는 방어용 여유)
const MAXIMUM_TITLE_LENGTH = 80;
// 공지 최대 글자 수 (Flask 검증과 같음)
const MAXIMUM_NOTICE_LENGTH = 300;
const NOTICE_LEVELS = new Set(Object.values(NoticeLevel));

/** 스냅샷 > {title, notice: {text, level} | null} */
export function readPageSettings(config) {
  const page = isPlainObject(config?.page) ? config.page : {};
  return { title: readTitle(page.title), notice: readNotice(page.notice) };
}

/** 제목: 앞뒤 공백 제거, 비었거나 문자열 아니면 기본값 */
function readTitle(title) {
  const trimmedTitle = typeof title === 'string' ? title.trim() : '';
  return trimmedTitle === '' ? DEFAULT_SITE_TITLE : trimmedTitle.slice(0, MAXIMUM_TITLE_LENGTH);
}

/** 공지: 문구 없으면 null, 수준 모르면 info */
function readNotice(notice) {
  if (!isPlainObject(notice) || typeof notice.text !== 'string') return null;
  const text = notice.text.trim().slice(0, MAXIMUM_NOTICE_LENGTH);
  if (text === '') return null;
  return { text, level: NOTICE_LEVELS.has(notice.level) ? notice.level : NoticeLevel.INFO };
}
