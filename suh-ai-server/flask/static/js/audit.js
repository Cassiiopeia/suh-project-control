/* 감사로그 전용 페이지 — 구조화 테이블 + 필터 + 키셋 페이징 + 자동 새로고침(10초)
   행위 라벨은 여기서만 관리한다: AuditAction enum 추가 시 ACTION_LABELS에 한 줄 추가 (없으면 코드 원문 표시) */
(function () {
  var API = '../audit/logs';

  var CATEGORY_META = {
    PALWORLD: { label: '팰월드', badge: 'badge-primary' },
    TTS: { label: 'TTS', badge: 'badge-secondary' },
    MODEL: { label: '모델', badge: 'badge-accent' },
    SYSTEM: { label: '시스템', badge: 'badge-neutral' },
  };

  var ACTION_LABELS = {
    SERVER_START: '팰월드 서버 시작',
    SERVER_STOP: '팰월드 서버 중지',
    SERVER_RESTART: '팰월드 서버 재시작',
    SETTINGS_UPDATE: '팰월드 설정 변경',
    BACKUP_CREATE: '팰월드 백업 생성',
    SERVER_UPDATE: '팰월드 서버 업데이트',
    TTS_INSTALL: 'TTS 엔진 설치',
    TTS_START: 'TTS 엔진 시작',
    TTS_STOP: 'TTS 엔진 중지',
    TTS_VOICE_ADD: 'TTS 보이스 등록',
    TTS_VOICE_DELETE: 'TTS 보이스 삭제',
    MODEL_DELETE: '모델 삭제',
    MODEL_DOWNLOAD: '모델 다운로드',
    MODEL_DOWNLOAD_CANCEL: '모델 다운로드 취소',
  };

  // 카테고리 선택 시 행위 셀렉트를 해당 카테고리 것만으로 좁힌다
  var ACTIONS_BY_CATEGORY = {
    PALWORLD: ['SERVER_START', 'SERVER_STOP', 'SERVER_RESTART', 'SETTINGS_UPDATE',
               'BACKUP_CREATE', 'SERVER_UPDATE'],
    TTS: ['TTS_INSTALL', 'TTS_START', 'TTS_STOP', 'TTS_VOICE_ADD', 'TTS_VOICE_DELETE'],
    MODEL: ['MODEL_DELETE', 'MODEL_DOWNLOAD', 'MODEL_DOWNLOAD_CANCEL'],
    SYSTEM: [],
  };

  var KST_FMT = new Intl.DateTimeFormat('ko-KR', {
    timeZone: 'Asia/Seoul', month: '2-digit', day: '2-digit',
    hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false,
  });
  var KST_FULL = new Intl.DateTimeFormat('ko-KR', {
    timeZone: 'Asia/Seoul', year: 'numeric', month: '2-digit', day: '2-digit',
    hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false,
  });

  var rowsEl = document.getElementById('audit-rows');
  var metaEl = document.getElementById('audit-meta');
  var countEl = document.getElementById('audit-count');
  var moreBtn = document.getElementById('audit-more');
  var lastId = null;     // 키셋 페이징 커서 (표시 중인 가장 오래된 id)
  var shownCount = 0;

  function filters() {
    return {
      category: document.getElementById('audit-category').value,
      action: document.getElementById('audit-action').value,
      success: document.getElementById('audit-success').value,
      search: document.getElementById('audit-search').value.trim(),
    };
  }

  function buildUrl(beforeId) {
    var f = filters();
    var params = new URLSearchParams({ limit: '100' });
    if (f.category) params.set('category', f.category);
    if (f.action) params.set('action', f.action);
    if (f.success) params.set('success', f.success);
    if (f.search) params.set('search', f.search);
    if (beforeId) params.set('before_id', String(beforeId));
    return API + '?' + params.toString();
  }

  function syncActionOptions() {
    var category = document.getElementById('audit-category').value;
    var actionEl = document.getElementById('audit-action');
    var keys = category ? (ACTIONS_BY_CATEGORY[category] || []) : Object.keys(ACTION_LABELS);
    actionEl.innerHTML = '<option value="">전체 행위</option>' + keys.map(function (k) {
      return '<option value="' + k + '">' + (ACTION_LABELS[k] || k) + '</option>';
    }).join('');
  }

  function actionLabel(row) {
    var label = ACTION_LABELS[row.action] || row.action;  // 미등록 action은 코드 원문
    var d = row.detail || {};
    var suffix = d.engine || d.name || d.voice_id || null;
    return suffix ? label + ' (' + suffix + ')' : label;
  }

  function detailHtml(detail) {
    if (detail && typeof detail === 'object' && detail.changed &&
        typeof detail.changed === 'object') {
      // 설정 diff는 key: from → to 목록으로
      var items = Object.keys(detail.changed).map(function (key) {
        var v = detail.changed[key] || {};
        var from = (v && typeof v === 'object') ? v.from : '';
        var to = (v && typeof v === 'object') ? v.to : v;
        return '<div class="font-mono text-xs">' + escapeHtml(key) + ': ' +
          escapeHtml(String(from)) + ' → ' + escapeHtml(String(to)) + '</div>';
      }).join('');
      var applied = detail.applied === false
        ? '<div class="text-xs opacity-60 mt-1">재시작/중지 시 적용 예정(pending)</div>' : '';
      return items + applied;
    }
    return '<pre class="text-xs whitespace-pre-wrap">' +
      escapeHtml(JSON.stringify(detail, null, 2)) + '</pre>';
  }

  function appendRows(rows) {
    rows.forEach(function (row) {
      var cat = CATEGORY_META[row.category] || { label: row.category, badge: 'badge-ghost' };
      var when = new Date(row.occurred_at);
      var tr = document.createElement('tr');
      var proxyTip = (row.proxy_chain && row.proxy_chain.length)
        ? '경유: ' + row.proxy_chain.join(' → ') : '';
      var uaTip = row.user_agent ? 'UA: ' + row.user_agent : '';
      var ipTitle = [proxyTip, uaTip].filter(Boolean).join('\n');
      tr.innerHTML =
        '<td class="whitespace-nowrap font-mono text-xs" title="' +
          escapeHtml(KST_FULL.format(when)) + '">' + escapeHtml(KST_FMT.format(when)) + '</td>' +
        '<td><span class="badge badge-sm ' + cat.badge + '">' + escapeHtml(cat.label) + '</span></td>' +
        '<td>' + escapeHtml(actionLabel(row)) + '</td>' +
        '<td class="font-mono text-xs" title="' + escapeHtml(ipTitle) + '">' +
          escapeHtml(row.client_ip || '-') +
          (ipTitle ? ' <i data-lucide="info" class="size-3 inline opacity-50"></i>' : '') + '</td>' +
        '<td>' + (row.success
          ? '<span class="badge badge-sm badge-success">성공</span>'
          : '<span class="badge badge-sm badge-error">실패</span>') + '</td>' +
        '<td class="text-right">' + (row.detail
          ? '<button type="button" class="btn btn-ghost btn-xs" data-role="toggle">상세</button>'
          : '') + '</td>';
      rowsEl.appendChild(tr);
      if (row.detail) {
        var detailTr = document.createElement('tr');
        detailTr.className = 'hidden';
        var td = document.createElement('td');
        td.colSpan = 6;
        td.className = 'bg-base-200';
        td.innerHTML = detailHtml(row.detail);
        detailTr.appendChild(td);
        rowsEl.appendChild(detailTr);
        tr.querySelector('[data-role="toggle"]').addEventListener('click', function () {
          detailTr.classList.toggle('hidden');
        });
        tr.classList.add('cursor-pointer');
        tr.addEventListener('click', function (e) {
          if (e.target.closest('button')) return;  // 버튼 클릭과 중복 토글 방지
          detailTr.classList.toggle('hidden');
        });
      }
      lastId = row.id;
      shownCount++;
    });
  }

  async function load(more) {
    var resp;
    try {
      resp = await apiFetch(buildUrl(more ? lastId : null));
    } catch (e) { return; /* 401은 apiFetch가 modal 처리 */ }
    var data = await resp.json();
    if (!more) { rowsEl.innerHTML = ''; lastId = null; shownCount = 0; }
    if (data.available === false) {
      metaEl.textContent = '';
      countEl.textContent = '';
      rowsEl.innerHTML = '<tr><td colspan="6" class="text-center opacity-60">' +
        '감사 DB에 연결할 수 없습니다: ' + escapeHtml(data.location || '') + '</td></tr>';
      moreBtn.classList.add('hidden');
      return;
    }
    appendRows(data.rows || []);
    if (!shownCount) {
      rowsEl.innerHTML = '<tr><td colspan="6" class="text-center opacity-60">' +
        '조건에 맞는 감사로그가 없습니다</td></tr>';
    }
    metaEl.textContent = data.location || '';
    countEl.textContent = shownCount ? shownCount + '건 표시' + (data.has_more ? ' (더 있음)' : '') : '';
    moreBtn.classList.toggle('hidden', !data.has_more);
    if (window.lucide) lucide.createIcons();
  }

  document.getElementById('audit-category').addEventListener('change', function () {
    syncActionOptions(); load(false);
  });
  document.getElementById('audit-action').addEventListener('change', function () { load(false); });
  document.getElementById('audit-success').addEventListener('change', function () { load(false); });
  document.getElementById('audit-search').addEventListener('change', function () { load(false); });
  document.getElementById('audit-refresh').addEventListener('click', function () { load(false); });
  moreBtn.addEventListener('click', function () { load(true); });

  setInterval(function () {
    // 페이징으로 과거를 보는 중이면 자동 새로고침이 목록을 리셋하지 않게 첫 페이지일 때만
    if (document.getElementById('audit-auto').checked && !document.hidden && shownCount <= 100) {
      load(false);
    }
  }, 10000);

  document.addEventListener('DOMContentLoaded', function () {
    syncActionOptions();
    load(false);
  });
})();
