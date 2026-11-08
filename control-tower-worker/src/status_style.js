/**
 * 공개 status 페이지 인라인 CSS: :root 색·간격 토큰 > 다크 모드 덮어쓰기 > 기본·머리·배너·공지·진행 중 장애
 * 상태색(ok·warn·bad·maintenance)과 브랜드 주황은 여기 토큰에만 정의, 배경 틴트는 color-mix로 파생
 * 묶음·막대·툴팁·14일 목록·바닥·좁은 화면 규칙은 status_style_groups.js
 */
import { STATUS_GROUP_CSS } from './status_style_groups.js';

// 페이지 바탕색 (CSS 토큰 + theme-color 메타 공통 원본)
export const PAGE_BACKGROUND_COLOR_LIGHT = '#F6F6F7';
export const PAGE_BACKGROUND_COLOR_DARK = '#0E0E10';

const STATUS_BASE_CSS = `
:root {
  --color-ok: #30A46C;
  --color-warn: #F5A524;
  --color-bad: #E5484D;
  --color-maintenance: #3E63DD;
  --color-info: #3E63DD;
  --color-brand: #F59E2B;
  --color-logo-tile: #151515;
  --color-tile-0: #3E63DD;
  --color-tile-1: #30A46C;
  --color-tile-2: #D6409F;
  --color-tile-3: #E5484D;
  --color-tile-4: #8E4EC6;
  --color-tile-5: #0D9B8A;
  --color-tile-6: #C27803;
  --color-tile-7: #5B6B7B;
  --color-on-state: #FFFFFF;
  --color-none: #DDDDE2;
  --color-background: ${PAGE_BACKGROUND_COLOR_LIGHT};
  --color-surface: #FFFFFF;
  --color-surface-raised: #FAFAFB;
  --color-text: #18181B;
  --color-text-muted: #6B6B74;
  --color-border: #E4E4E9;
  --color-tooltip-background: #18181B;
  --color-tooltip-text: #FAFAFA;
  --shadow-card: 0 1px 2px rgba(16, 16, 24, 0.04), 0 1px 1px rgba(16, 16, 24, 0.03);
  --space-1: 4px;
  --space-2: 8px;
  --space-3: 12px;
  --space-4: 16px;
  --space-5: 20px;
  --space-6: 24px;
  --space-8: 32px;
  --space-10: 40px;
  --radius-small: 6px;
  --radius-logo: 10px;
  --radius-card: 14px;
  --radius-hero: 18px;
  --radius-pill: 999px;
  --font-size-tiny: 12px;
  --font-size-small: 13px;
  --font-size-body: 15px;
  --font-size-section: 16px;
  --font-size-hero: 20px;
  --font-size-title: 18px;
  --logo-size: 36px;
  --thumb-size: 40px;
  --bar-height: 32px;
  --page-max-width: 820px;
}
@media (prefers-color-scheme: dark) {
  :root {
    --color-none: #2E2E34;
    --color-tile-0: #7C9BFF;
    --color-tile-1: #4CC38A;
    --color-tile-2: #F06FBE;
    --color-tile-3: #FF7B80;
    --color-tile-4: #B98BE6;
    --color-tile-5: #3CC9B7;
    --color-tile-6: #F5B94D;
    --color-tile-7: #9FB0C0;
    --color-background: ${PAGE_BACKGROUND_COLOR_DARK};
    --color-surface: #17171A;
    --color-surface-raised: #1C1C20;
    --color-text: #EDEDEF;
    --color-text-muted: #9E9EA8;
    --color-border: #27272C;
    --color-tooltip-background: #F4F4F5;
    --color-tooltip-text: #18181B;
    --shadow-card: none;
  }
}
* { box-sizing: border-box; }
html { -webkit-text-size-adjust: 100%; }
body {
  margin: 0;
  background: var(--color-background);
  color: var(--color-text);
  font-family: -apple-system, BlinkMacSystemFont, "Pretendard", "Apple SD Gothic Neo", "Segoe UI", "Malgun Gothic", "Noto Sans KR", Roboto, sans-serif;
  font-size: var(--font-size-body);
  line-height: 1.55;
  letter-spacing: -0.005em;
  -webkit-font-smoothing: antialiased;
  font-variant-numeric: tabular-nums;
  word-break: keep-all;
}
.page { max-width: var(--page-max-width); margin: 0 auto; padding: var(--space-8) var(--space-5) var(--space-10); }
h2 { margin: 0; font-size: var(--font-size-section); font-weight: 700; letter-spacing: -0.01em; }
.section-title { margin: var(--space-8) 0 var(--space-3); display: flex; align-items: baseline; justify-content: space-between; gap: var(--space-3); }
.section-title small { color: var(--color-text-muted); font-size: var(--font-size-small); font-weight: 500; }
.state-up { --state-color: var(--color-ok); }
.state-degraded { --state-color: var(--color-warn); }
.state-down { --state-color: var(--color-bad); }
.state-maintenance { --state-color: var(--color-maintenance); }
.state-unknown { --state-color: var(--color-text-muted); }
.dot { display: inline-block; flex: none; width: 10px; height: 10px; border-radius: 50%; background: var(--state-color); }
.site-header { display: flex; align-items: center; justify-content: space-between; gap: var(--space-3); margin-bottom: var(--space-6); }
.brand { display: flex; align-items: center; gap: var(--space-3); min-width: 0; color: inherit; text-decoration: none; }
.brand-logo {
  flex: none; width: var(--logo-size); height: var(--logo-size); border-radius: var(--radius-logo);
  background: var(--color-logo-tile);
  box-shadow: 0 0 0 1px color-mix(in srgb, var(--color-brand) 35%, transparent);
}
.brand-name { margin: 0; font-size: var(--font-size-title); font-weight: 750; letter-spacing: -0.02em; overflow-wrap: anywhere; }
.live-chip {
  display: inline-flex; align-items: center; gap: var(--space-2); flex: none;
  padding: var(--space-1) var(--space-3); border: 1px solid var(--color-border); border-radius: var(--radius-pill);
  background: var(--color-surface); color: var(--color-text-muted); font-size: var(--font-size-tiny); font-weight: 600;
}
.live-chip .dot { width: 7px; height: 7px; animation: live-pulse 2.4s ease-in-out infinite; }
@keyframes live-pulse { 50% { opacity: 0.35; } }
@media (prefers-reduced-motion: reduce) { .live-chip .dot { animation: none; } }
.hero {
  display: flex; align-items: center; gap: var(--space-4);
  padding: var(--space-5) var(--space-6); border-radius: var(--radius-hero);
  background: color-mix(in srgb, var(--state-color) 10%, var(--color-surface));
  border: 1px solid color-mix(in srgb, var(--state-color) 32%, transparent);
  box-shadow: var(--shadow-card);
}
.hero-icon {
  display: grid; place-items: center; flex: none; width: 40px; height: 40px; border-radius: 50%;
  background: var(--state-color); color: var(--color-on-state); font-size: var(--font-size-hero); font-weight: 800; line-height: 1;
  box-shadow: 0 0 0 6px color-mix(in srgb, var(--state-color) 18%, transparent);
}
.hero-message { margin: 0; font-size: var(--font-size-hero); font-weight: 750; letter-spacing: -0.02em; }
.hero-detail { margin: 2px 0 0; color: var(--color-text-muted); font-size: var(--font-size-small); }
.notice {
  display: flex; align-items: flex-start; gap: var(--space-3);
  margin: var(--space-3) 0 0; padding: var(--space-3) var(--space-4);
  border-radius: var(--radius-card); border: 1px solid color-mix(in srgb, var(--notice-color) 30%, var(--color-border));
  border-left: 4px solid var(--notice-color);
  background: color-mix(in srgb, var(--notice-color) 7%, var(--color-surface));
  font-size: var(--font-size-small);
}
.notice-info { --notice-color: var(--color-info); }
.notice-warning { --notice-color: var(--color-warn); }
.notice-critical { --notice-color: var(--color-bad); }
.notice-label {
  flex: none; padding: 1px var(--space-2); border-radius: var(--radius-small);
  background: var(--notice-color); color: var(--color-on-state); font-size: var(--font-size-tiny); font-weight: 700;
}
.notice-text { margin: 0; overflow-wrap: anywhere; white-space: pre-line; }
.notice-delayed { --notice-color: var(--color-text-muted); color: var(--color-text-muted); }
.active-incidents {
  margin-top: var(--space-3); padding: var(--space-4) var(--space-5);
  border-radius: var(--radius-card); background: var(--color-surface);
  border: 1px solid color-mix(in srgb, var(--color-bad) 35%, var(--color-border)); border-left: 4px solid var(--color-bad);
  box-shadow: var(--shadow-card);
}
.active-incidents h2 { color: var(--color-bad); font-size: var(--font-size-body); }
.active-incident-list { margin: var(--space-2) 0 0; padding: 0; list-style: none; }
.active-incident { display: flex; flex-wrap: wrap; justify-content: space-between; gap: var(--space-1) var(--space-3); padding: var(--space-2) 0; border-top: 1px solid var(--color-border); }
.active-incident:first-child { border-top: 0; }
.active-incident-name { font-weight: 650; overflow-wrap: anywhere; }
.active-incident-time { color: var(--color-text-muted); font-size: var(--font-size-small); }
`;

export const STATUS_PAGE_CSS = STATUS_BASE_CSS + STATUS_GROUP_CSS;
