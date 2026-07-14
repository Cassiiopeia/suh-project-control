/* 공용 로그 뷰어 — 팰월드 로그 탭 / Flask 로그 페이지에서 사용.
   소스 전환, 라인 수, 자동 새로고침(10초), 검색어 필터 + 매칭 하이라이트,
   레벨 필터(전체/에러/경고), 맨 아래일 때만 자동 스크롤, 파일 경로·크기 표시. */
function createLogViewer(rootEl, config) {
  var sources = config.sources;
  var currentSource = sources[0].id;
  var lines = 200;
  var query = '';
  var levelFilter = 'all';   // all | error | warn
  var hideNoise = true;      // REST 폴링 잡음 등 반복 라인 숨기기 (기본 ON)
  var lastLogs = [];         // 마지막으로 받은 원본 로그 (필터 변경 시 재요청 없이 재렌더)
  var lastMeta = null;
  // 잡음 패턴: 우리 폴러가 만드는 REST 접근 로그 등. config로 덮어쓸 수 있다.
  var noiseRe = config.noisePattern || /REST accessed endpoint/i;

  rootEl.innerHTML =
    '<div class="flex flex-wrap items-center gap-2 mb-3">' +
    '<div role="tablist" class="tabs tabs-box tabs-sm" data-role="sources"></div>' +
    '<label class="input input-sm flex items-center gap-1 w-44">' +
    '<i data-lucide="search" class="size-4 opacity-60"></i>' +
    '<input type="text" class="grow" placeholder="검색" data-role="search">' +
    '</label>' +
    '<select class="select select-sm w-24" data-role="level">' +
    '<option value="all">전체</option><option value="error">에러</option><option value="warn">경고</option>' +
    '</select>' +
    '<select class="select select-sm w-28" data-role="lines">' +
    '<option value="100">100줄</option><option value="200" selected>200줄</option><option value="500">500줄</option>' +
    '</select>' +
    '<label class="label cursor-pointer gap-2 text-sm" data-role="noise-wrap">' +
    '<input type="checkbox" class="toggle toggle-sm toggle-primary" data-role="noise" checked><span>잡음 숨기기</span>' +
    '</label>' +
    '<label class="label cursor-pointer gap-2 text-sm">' +
    '<input type="checkbox" class="toggle toggle-sm toggle-primary" data-role="auto" checked><span>자동 새로고침</span>' +
    '</label>' +
    '<button type="button" class="btn btn-ghost btn-sm" data-role="refresh">' +
    '<i data-lucide="refresh-cw" class="size-4"></i>새로고침</button>' +
    '</div>' +
    '<div class="flex items-center justify-between text-xs opacity-60 mb-2 gap-2">' +
    '<span class="font-mono break-all" data-role="meta"></span>' +
    '<span data-role="count" class="shrink-0"></span>' +
    '</div>' +
    '<pre class="bg-base-300 rounded-box text-xs leading-5 overflow-auto max-h-[28rem] p-4" data-role="view">불러오는 중…</pre>';

  var sourcesEl = rootEl.querySelector('[data-role="sources"]');
  var viewEl = rootEl.querySelector('[data-role="view"]');
  var metaEl = rootEl.querySelector('[data-role="meta"]');
  var countEl = rootEl.querySelector('[data-role="count"]');

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
  // 검색·레벨 필터는 재요청 없이 마지막 로그를 다시 렌더 (즉각 반응)
  rootEl.querySelector('[data-role="search"]').addEventListener('input', function (e) {
    query = e.target.value; render();
  });
  rootEl.querySelector('[data-role="level"]').addEventListener('change', function (e) {
    levelFilter = e.target.value; render();
  });
  rootEl.querySelector('[data-role="noise"]').addEventListener('change', function (e) {
    hideNoise = e.target.checked; refresh();  // 서버측 필터 창이 달라져 재요청 필요
  });

  function levelClass(line) {
    if (/error|fatal|fail/i.test(line)) return 'text-error';
    if (/warn/i.test(line)) return 'text-warning';
    return '';
  }

  function matchesLevel(line) {
    if (levelFilter === 'all') return true;
    if (levelFilter === 'error') return /error|fatal|fail/i.test(line);
    if (levelFilter === 'warn') return /warn/i.test(line);
    return true;
  }

  function escapeRe(s) { return s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'); }

  /* 한 줄을 텍스트 노드 + 하이라이트 <mark>로 쪼개 span에 담는다 (XSS 없이 안전) */
  function appendLine(text, cls) {
    var span = document.createElement('span');
    if (cls) span.className = cls;
    if (query) {
      var re = new RegExp('(' + escapeRe(query) + ')', 'ig');
      var parts = text.split(re);
      parts.forEach(function (part, i) {
        if (i % 2 === 1) {
          var mark = document.createElement('mark');
          mark.className = 'bg-warning text-warning-content rounded px-0.5';
          mark.textContent = part;
          span.appendChild(mark);
        } else if (part) {
          span.appendChild(document.createTextNode(part));
        }
      });
      span.appendChild(document.createTextNode('\n'));
    } else {
      span.textContent = text + '\n';
    }
    viewEl.appendChild(span);
  }

  /* lastLogs를 현재 검색/레벨 필터로 렌더 (네트워크 요청 없음) */
  function render() {
    if (lastMeta === false) {
      metaEl.textContent = '';
      countEl.textContent = '';
      return;
    }
    var atBottom = viewEl.scrollHeight - viewEl.scrollTop - viewEl.clientHeight < 40;
    var q = query.toLowerCase();
    viewEl.textContent = '';
    var shown = 0;
    lastLogs.forEach(function (line) {
      var text = config.formatLine ? config.formatLine(line, currentSource) : line;
      if (hideNoise && noiseRe.test(text)) return;
      if (!matchesLevel(text)) return;
      if (q && text.toLowerCase().indexOf(q) === -1) return;
      appendLine(text, levelClass(text));
      shown++;
    });
    if (!shown) {
      viewEl.textContent = (query || levelFilter !== 'all') ? '(필터에 맞는 로그 없음)' : '(로그 없음)';
    }
    countEl.textContent = lastLogs.length ? (shown + ' / ' + lastLogs.length + ' 줄') : '';
    if (atBottom) viewEl.scrollTop = viewEl.scrollHeight;
  }

  async function refresh() {
    var data;
    try {
      data = await config.fetchLogs(currentSource, lines, hideNoise);
    } catch (e) { return; /* 401은 apiFetch가 modal 처리 */ }
    if (data.exists === false) {
      lastMeta = false;
      lastLogs = [];
      metaEl.textContent = '';
      countEl.textContent = '';
      viewEl.textContent = '로그 파일이 아직 없습니다: ' + (data.log_file || '(경로 미상)');
      return;
    }
    lastMeta = data;
    lastLogs = data.logs || [];
    metaEl.textContent = data.log_file
      ? data.log_file + ' (' + ((data.size_bytes || 0) / 1024 / 1024).toFixed(1) + ' MB)'
      : '';
    render();
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
