/**
 * HTML 이스케이프 공통 (공개 페이지 본문·속성 값)
 */
const HTML_ESCAPE_BY_CHARACTER = Object.freeze({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' });

/** 문자열 HTML 이스케이프 (& < > " ') */
export function escapeHtml(value) {
  return String(value ?? '').replace(/[&<>"']/g, (character) => HTML_ESCAPE_BY_CHARACTER[character]);
}
