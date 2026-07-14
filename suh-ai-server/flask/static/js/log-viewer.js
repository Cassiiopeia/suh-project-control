/* 공용 로그 뷰어 — 팰월드 로그 탭 / Flask 로그 페이지에서 사용.
   소스 전환, 라인 수, 자동 새로고침(10초), Error/Warning 하이라이트,
   맨 아래일 때만 자동 스크롤, 파일 경로·크기 표시, 파일 없으면 경로 안내. */
function createLogViewer(rootEl, config) {
  var sources = config.sources;
  var currentSource = sources[0].id;
  var lines = 200;

  rootEl.innerHTML =
    '<div class="flex flex-wrap items-center gap-2 mb-3">' +
    '<div role="tablist" class="tabs tabs-box tabs-sm" data-role="sources"></div>' +
    '<select class="select select-sm w-28" data-role="lines">' +
    '<option value="100">100줄</option><option value="200" selected>200줄</option><option value="500">500줄</option>' +
    '</select>' +
    '<label class="label cursor-pointer gap-2 text-sm">' +
    '<input type="checkbox" class="toggle toggle-sm toggle-primary" data-role="auto" checked><span>자동 새로고침</span>' +
    '</label>' +
    '<button type="button" class="btn btn-ghost btn-sm" data-role="refresh">' +
    '<i data-lucide="refresh-cw" class="size-4"></i>새로고침</button>' +
    '</div>' +
    '<div class="text-xs opacity-60 mb-2 font-mono break-all" data-role="meta"></div>' +
    '<pre class="bg-base-300 rounded-box text-xs leading-5 overflow-auto max-h-[28rem] p-4" data-role="view">불러오는 중…</pre>';

  var sourcesEl = rootEl.querySelector('[data-role="sources"]');
  var viewEl = rootEl.querySelector('[data-role="view"]');
  var metaEl = rootEl.querySelector('[data-role="meta"]');

  sources.forEach(function (s) {
    var tab = document.createElement('button');
    tab.type = 'button';
    tab.setAttribute('role', 'tab');
    tab.className = 'tab' + (s.id === currentSource ? ' tab-active' : '');
    tab.textContent = s.label;
    tab.addEventListener('click', function () {
      currentSource = s.id;
      sourcesEl.querySelectorAll('.tab').forEach(function (t) { t.classList.remove('tab-active'); });
      tab.classList.add('tab-active');
      refresh();
    });
    sourcesEl.appendChild(tab);
  });
  if (sources.length < 2) sourcesEl.classList.add('hidden');

  rootEl.querySelector('[data-role="lines"]').addEventListener('change', function (e) {
    lines = parseInt(e.target.value, 10);
    refresh();
  });
  rootEl.querySelector('[data-role="refresh"]').addEventListener('click', function () { refresh(); });

  function levelClass(line) {
    if (/error|fatal|fail/i.test(line)) return 'text-error';
    if (/warn/i.test(line)) return 'text-warning';
    return '';
  }

  async function refresh() {
    var data;
    try {
      data = await config.fetchLogs(currentSource, lines);
    } catch (e) { return; /* 401은 apiFetch가 modal 처리 */ }
    var atBottom = viewEl.scrollHeight - viewEl.scrollTop - viewEl.clientHeight < 40;
    if (data.exists === false) {
      metaEl.textContent = '';
      viewEl.textContent = '로그 파일이 아직 없습니다: ' + (data.log_file || '(경로 미상)');
      return;
    }
    metaEl.textContent = data.log_file
      ? data.log_file + ' (' + ((data.size_bytes || 0) / 1024 / 1024).toFixed(1) + ' MB)'
      : '';
    var logs = data.logs || [];
    viewEl.textContent = '';
    if (!logs.length) {
      viewEl.textContent = '(로그 없음)';
      return;
    }
    logs.forEach(function (line) {
      var span = document.createElement('span');
      var text = config.formatLine ? config.formatLine(line, currentSource) : line;
      span.textContent = text + '\n';
      var cls = levelClass(text);
      if (cls) span.className = cls;
      viewEl.appendChild(span);
    });
    if (atBottom) viewEl.scrollTop = viewEl.scrollHeight;
  }

  setInterval(function () {
    if (rootEl.querySelector('[data-role="auto"]').checked && !document.hidden) refresh();
  }, 10000);

  refresh();
  if (window.lucide) lucide.createIcons();
  return { refresh: refresh };
}

/* 팰월드 이벤트 JSONL 한 줄 → 한국어 문장 (파싱 실패 시 원문 그대로) */
function formatPalworldEvent(line) {
  try {
    var e = JSON.parse(line);
    if (e.type === 'join' || e.type === 'leave') {
      var name = (e.player && e.player.name) || '?';
      var verb = e.type === 'join' ? '접속' : '퇴장';
      return '[' + e.ts + "] '" + name + "' " + verb + ' (현재 ' + e.count + '명)';
    }
    if (e.type === 'server_up') return '[' + e.ts + '] 서버가 시작되었습니다';
    if (e.type === 'server_down') return '[' + e.ts + '] 서버가 중지되었습니다';
    return line;
  } catch (err) {
    return line;
  }
}
