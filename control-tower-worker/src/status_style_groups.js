/**
 * 공개 status 페이지 CSS (2): 프로젝트 묶음(details)·썸네일·서비스 행·90일 막대·CSS 툴팁·범례·14일 목록·바닥·좁은 화면
 * 색은 status_style.js :root 토큰만 사용, 툴팁은 data-tip + ::after (JS 없음)
 * 좁은 화면(600px 이하)은 막대 60칸만 표시 (360px에서 가로 스크롤 없음)
 */
export const STATUS_GROUP_CSS = `
.groups { display: grid; gap: var(--space-3); }
.group {
  border-radius: var(--radius-card); border: 1px solid var(--color-border);
  background: var(--color-surface); box-shadow: var(--shadow-card);
}
.group-summary {
  display: flex; align-items: center; gap: var(--space-3);
  padding: var(--space-4) var(--space-5); cursor: pointer; list-style: none; border-radius: var(--radius-card);
}
.group-summary::-webkit-details-marker { display: none; }
.group-summary:hover { background: var(--color-surface-raised); }
.group-summary:focus-visible { outline: 2px solid var(--color-brand); outline-offset: 2px; }
.chevron {
  flex: none; width: 8px; height: 8px; margin: 0 2px;
  border-right: 2px solid var(--color-text-muted); border-bottom: 2px solid var(--color-text-muted);
  transform: rotate(-45deg); transition: transform 0.15s ease;
}
.group[open] .chevron { transform: rotate(45deg); }
.group-thumb {
  flex: none; width: var(--thumb-size); height: var(--thumb-size);
  border-radius: var(--radius-logo); object-fit: cover; background: var(--color-surface-raised);
  border: 1px solid var(--color-border);
}
.group-thumb-tile {
  display: inline-flex; align-items: center; justify-content: center;
  border-color: transparent; font-weight: 700; font-size: var(--font-size-section);
  background: color-mix(in srgb, var(--tile-color) 16%, transparent);
  color: color-mix(in srgb, var(--tile-color) 80%, var(--color-text));
}
.tile-0 { --tile-color: var(--color-tile-0); }
.tile-1 { --tile-color: var(--color-tile-1); }
.tile-2 { --tile-color: var(--color-tile-2); }
.tile-3 { --tile-color: var(--color-tile-3); }
.tile-4 { --tile-color: var(--color-tile-4); }
.tile-5 { --tile-color: var(--color-tile-5); }
.tile-6 { --tile-color: var(--color-tile-6); }
.tile-7 { --tile-color: var(--color-tile-7); }
.group-title { display: flex; flex-direction: column; min-width: 0; flex: 1 1 auto; }
.group-name { font-weight: 700; overflow-wrap: anywhere; }
.group-meta { color: var(--color-text-muted); font-size: var(--font-size-tiny); }
.group-uptime { flex: none; color: var(--color-text-muted); font-size: var(--font-size-small); font-weight: 600; }
.group-body { padding: 0 var(--space-5) var(--space-2); border-top: 1px solid var(--color-border); }
.service { padding: var(--space-3) 0; border-top: 1px solid var(--color-border); }
.service:first-child { border-top: 0; }
.service-head { display: flex; align-items: center; justify-content: space-between; gap: var(--space-2); margin-bottom: var(--space-2); }
.service-name { min-width: 0; overflow-wrap: anywhere; font-weight: 600; }
.pill {
  display: inline-flex; align-items: center; gap: 6px; flex: none;
  padding: 2px 10px; border-radius: var(--radius-pill);
  background: color-mix(in srgb, var(--state-color) 13%, transparent);
  color: color-mix(in srgb, var(--state-color) 70%, var(--color-text));
  font-size: var(--font-size-tiny); font-weight: 700; white-space: nowrap;
}
.pill .dot { width: 7px; height: 7px; }
.bars { display: flex; gap: 2px; height: var(--bar-height); }
.bar-cell { position: relative; flex: 1 1 0; min-width: 0; border-radius: 2px; background: var(--color-none); }
.bar-cell.ok { background: var(--color-ok); }
.bar-cell.warn { background: var(--color-warn); }
.bar-cell.bad { background: var(--color-bad); }
.bar-cell:hover { outline: 1px solid var(--color-text); outline-offset: 1px; }
.bar-cell:hover::after {
  content: attr(data-tip);
  position: absolute; bottom: calc(100% + 8px); left: 50%; z-index: 10; transform: translateX(-50%);
  padding: 6px 10px; border-radius: var(--radius-small);
  background: var(--color-tooltip-background); color: var(--color-tooltip-text);
  font-size: var(--font-size-tiny); font-weight: 600; line-height: 1.4; white-space: nowrap; pointer-events: none;
}
.bar-cell:nth-child(-n+12):hover::after { left: 0; transform: none; }
.bar-cell:nth-last-child(-n+12):hover::after { left: auto; right: 0; transform: none; }
.bar-caption {
  display: flex; justify-content: space-between; gap: var(--space-2);
  margin-top: 6px; color: var(--color-text-muted); font-size: var(--font-size-tiny);
}
.caption-short { display: none; }
.legend {
  display: flex; flex-wrap: wrap; justify-content: flex-end; gap: var(--space-2) var(--space-4);
  margin: var(--space-3) 0 0; padding: 0; list-style: none;
  color: var(--color-text-muted); font-size: var(--font-size-tiny);
}
.legend li { display: inline-flex; align-items: center; gap: 6px; }
.legend-swatch { width: 10px; height: 10px; border-radius: 2px; background: var(--color-none); }
.legend-swatch.ok { background: var(--color-ok); }
.legend-swatch.warn { background: var(--color-warn); }
.legend-swatch.bad { background: var(--color-bad); }
.history {
  border-radius: var(--radius-card); border: 1px solid var(--color-border);
  background: var(--color-surface); box-shadow: var(--shadow-card); padding: var(--space-1) var(--space-5);
}
.history-day { padding: var(--space-4) 0; border-top: 1px solid var(--color-border); }
.history-day:first-child { border-top: 0; }
.history-date { margin: 0 0 var(--space-2); font-size: var(--font-size-small); font-weight: 700; }
.history-empty { margin: 0; color: var(--color-text-muted); font-size: var(--font-size-small); }
.incidents { margin: 0; padding: 0; list-style: none; display: grid; gap: var(--space-2); }
.incident { padding-left: var(--space-3); border-left: 2px solid var(--state-color); }
.incident-head { display: flex; flex-wrap: wrap; align-items: center; gap: var(--space-2); }
.incident-name { font-weight: 600; overflow-wrap: anywhere; }
.incident-time { margin: 2px 0 0; color: var(--color-text-muted); font-size: var(--font-size-small); }
.footer {
  display: flex; flex-wrap: wrap; justify-content: space-between; gap: var(--space-2);
  margin-top: var(--space-8); padding-top: var(--space-4); border-top: 1px solid var(--color-border);
  color: var(--color-text-muted); font-size: var(--font-size-small);
}
.footer strong { color: var(--color-brand); font-weight: 700; }
@media (max-width: 600px) {
  .page { padding: var(--space-5) var(--space-4) var(--space-8); }
  .hero { padding: var(--space-4); gap: var(--space-3); }
  .hero-icon { width: 34px; height: 34px; }
  .hero-message { font-size: var(--font-size-section); }
  .live-chip { display: none; }
  .group-summary { padding: var(--space-3) var(--space-4); gap: var(--space-2); }
  .group-thumb { width: 34px; height: 34px; }
  .group-body { padding: 0 var(--space-4) var(--space-1); }
  .history { padding: var(--space-1) var(--space-4); }
  .bars { gap: 1px; }
  .bar-cell.older { display: none; }
  .bar-cell:nth-child(-n+46):hover::after { left: 0; transform: none; }
  .caption-long { display: none; }
  .caption-short { display: inline; }
  .legend { justify-content: flex-start; }
}
`;
