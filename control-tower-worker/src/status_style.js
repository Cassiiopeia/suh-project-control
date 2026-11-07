/**
 * 공개 status 페이지 인라인 CSS: :root 색·간격 토큰 > 다크 모드 중립색 덮어쓰기 > 배너·카드·막대·장애 목록
 * 상태색(ok·warn·bad·maintenance)은 여기 토큰에만 정의, 배경 틴트는 color-mix로 파생
 * 좁은 화면(600px 이하)은 막대 60칸만 표시 (360px에서 가로 스크롤 없음)
 */
export const STATUS_PAGE_CSS = `
:root {
  --color-ok: #30A46C;
  --color-warn: #F5A524;
  --color-bad: #E5484D;
  --color-maintenance: #3E63DD;
  --color-none: #DCDCE0;
  --color-background: #F7F7F8;
  --color-surface: #FFFFFF;
  --color-text: #1C1C1F;
  --color-text-muted: #6F6F78;
  --color-border: #E6E6EA;
  --space-1: 4px;
  --space-2: 8px;
  --space-3: 12px;
  --space-4: 16px;
  --space-6: 24px;
  --space-8: 32px;
  --radius-card: 14px;
  --radius-pill: 999px;
  --font-size-small: 13px;
  --font-size-body: 15px;
  --font-size-section: 17px;
  --font-size-title: 24px;
  --bar-height: 30px;
  --page-max-width: 760px;
}
@media (prefers-color-scheme: dark) {
  :root {
    --color-none: #3A3A40;
    --color-background: #111113;
    --color-surface: #1A1A1D;
    --color-text: #EDEDEF;
    --color-text-muted: #A0A0A8;
    --color-border: #2B2B30;
  }
}
* { box-sizing: border-box; }
body {
  margin: 0;
  background: var(--color-background);
  color: var(--color-text);
  font-family: -apple-system, BlinkMacSystemFont, "Apple SD Gothic Neo", "Pretendard", "Malgun Gothic", "Segoe UI", Roboto, sans-serif;
  font-size: var(--font-size-body);
  line-height: 1.5;
  -webkit-font-smoothing: antialiased;
}
.page { max-width: var(--page-max-width); margin: 0 auto; padding: var(--space-8) var(--space-4); }
.page-title { margin: 0 0 var(--space-6); font-size: var(--font-size-title); font-weight: 700; letter-spacing: -0.02em; }
h2 { margin: 0 0 var(--space-3); font-size: var(--font-size-section); font-weight: 650; }
.state-up { --state-color: var(--color-ok); }
.state-degraded { --state-color: var(--color-warn); }
.state-down { --state-color: var(--color-bad); }
.state-maintenance { --state-color: var(--color-maintenance); }
.state-unknown { --state-color: var(--color-text-muted); }
.dot { display: inline-block; flex: none; width: 10px; height: 10px; border-radius: 50%; background: var(--state-color); }
.banner {
  display: flex; align-items: center; gap: var(--space-3);
  padding: var(--space-4); margin-bottom: var(--space-4);
  border-radius: var(--radius-card);
  background: color-mix(in srgb, var(--state-color) 14%, var(--color-surface));
  border: 1px solid color-mix(in srgb, var(--state-color) 35%, transparent);
  font-weight: 650;
}
.notice {
  margin: 0 0 var(--space-4); padding: var(--space-3) var(--space-4);
  border-radius: var(--radius-card); border: 1px solid var(--color-border);
  background: var(--color-surface); color: var(--color-text-muted); font-size: var(--font-size-small);
}
.card {
  margin-bottom: var(--space-4); padding: var(--space-4) var(--space-4) var(--space-2);
  border-radius: var(--radius-card); border: 1px solid var(--color-border); background: var(--color-surface);
}
.service { padding: var(--space-3) 0; border-top: 1px solid var(--color-border); }
.service:first-of-type { border-top: 0; padding-top: 0; }
.service-head { display: flex; align-items: center; justify-content: space-between; gap: var(--space-2); margin-bottom: var(--space-2); }
.service-name { min-width: 0; overflow-wrap: anywhere; font-weight: 600; }
.pill {
  display: inline-flex; align-items: center; gap: var(--space-2); flex: none;
  padding: 2px var(--space-3); border-radius: var(--radius-pill);
  background: color-mix(in srgb, var(--state-color) 14%, transparent);
  font-size: var(--font-size-small); font-weight: 600; white-space: nowrap;
}
.pill .dot { width: 8px; height: 8px; }
.bars { display: flex; gap: 2px; height: var(--bar-height); }
.bar-cell { flex: 1 1 0; min-width: 0; border-radius: 2px; background: var(--color-none); }
.bar-cell.ok { background: var(--color-ok); }
.bar-cell.warn { background: var(--color-warn); }
.bar-cell.bad { background: var(--color-bad); }
.bar-cell:hover { opacity: 0.7; }
.bar-caption {
  display: flex; justify-content: space-between; gap: var(--space-2);
  margin-top: var(--space-1); color: var(--color-text-muted); font-size: var(--font-size-small);
}
.caption-short { display: none; }
.legend {
  display: flex; flex-wrap: wrap; gap: var(--space-2) var(--space-4);
  margin: 0 0 var(--space-6); padding: 0; list-style: none;
  color: var(--color-text-muted); font-size: var(--font-size-small);
}
.legend li { display: inline-flex; align-items: center; gap: var(--space-2); }
.legend-swatch { width: 10px; height: 10px; border-radius: 2px; background: var(--color-none); }
.legend-swatch.ok { background: var(--color-ok); }
.legend-swatch.warn { background: var(--color-warn); }
.legend-swatch.bad { background: var(--color-bad); }
.incidents { margin: 0; padding: 0; list-style: none; }
.incident { padding: var(--space-3) 0; border-top: 1px solid var(--color-border); }
.incident:first-child { border-top: 0; padding-top: 0; }
.incident-time, .empty { margin: var(--space-1) 0 0; color: var(--color-text-muted); font-size: var(--font-size-small); }
.empty { margin: 0 0 var(--space-2); }
.footer { margin-top: var(--space-6); color: var(--color-text-muted); font-size: var(--font-size-small); text-align: center; }
@media (max-width: 600px) {
  .page { padding: var(--space-6) var(--space-4); }
  .bars { gap: 1px; }
  .bar-cell.older { display: none; }
  .caption-long { display: none; }
  .caption-short { display: inline; }
}
`;
