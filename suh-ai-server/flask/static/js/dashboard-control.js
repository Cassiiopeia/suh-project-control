/* 대시보드 관제소 요약. base: /admin → API: ./control/overview
   흐름: 진입 시 조회 > 30초 폴링(탭 숨김 시 생략) > 상단 stat·카드 배지 갱신 */
(function () {
  const OVERVIEW_PATH = './control/overview';
  const POLL_INTERVAL_MILLISECONDS = 30000;

  function setText(id, value) {
    const element = document.getElementById(id);
    if (element) element.textContent = value;
  }

  /** 요약 > 상단 문구·설명·배지 (장애 있으면 빨강, 확인 필요만 있으면 노랑) */
  function renderControlSummary(overview) {
    const summary = overview.summary || {};
    const downCount = summary.down || 0;
    const okCount = summary.ok || 0;
    const isHeartbeatOk = !!(overview.heartbeat && overview.heartbeat.is_ok);
    setText('stat-control', downCount > 0 ? '장애 ' + downCount : '정상');
    setText('stat-control-desc', '정상 ' + okCount + ' · 점검 ' + (summary.maintenance || 0)
      + ' · 확인 필요 ' + (summary.needs_attention || 0) + (isHeartbeatOk ? '' : ' · Worker 응답 없음'));
    const badge = document.getElementById('control-badge');
    if (!badge) return;
    badge.textContent = downCount > 0 ? '장애 ' + downCount : '정상 ' + okCount;
    badge.className = 'badge badge-sm ' + (downCount > 0 ? 'badge-error' : 'badge-success');
  }

  async function refreshControlSummary() {
    try {
      const response = await apiFetch(OVERVIEW_PATH);
      if (!response.ok) { setText('stat-control', '오류'); return; }
      renderControlSummary(await response.json());
    } catch (error) {
      setText('stat-control', '오류');
    }
  }

  document.addEventListener('DOMContentLoaded', function () {
    refreshControlSummary();
    setInterval(function () { if (!document.hidden) refreshControlSummary(); }, POLL_INTERVAL_MILLISECONDS);
  });
})();
