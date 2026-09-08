/* Sunshine(Moonlight 호스트) 관리 페이지 스크립트. base: /admin/sunshine → API: ../sunshine/* */
(function () {
  const API = '../sunshine';

  let pendingUnpair = null;   // 해제 확인 모달에 걸린 {uuid, name}

  function el(id) { return document.getElementById(id); }

  /* ---------- 1. 상태 ---------- */
  async function loadStatus() {
    try {
      const resp = await apiFetch(API + '/status?t=' + Date.now());
      const data = await resp.json();
      if (!resp.ok) throw new Error(data.error || '상태 조회 실패');
      renderStatus(data);
    } catch (e) {
      console.warn('Sunshine status failed:', e);
      renderStatus(null);
    }
  }

  function renderStatus(s) {
    const svcBadge = el('svc-status-badge');
    const streamBadge = el('stream-state-badge');

    if (!s) {
      svcBadge.className = 'badge badge-ghost gap-1 text-xs py-2 px-2.5';
      svcBadge.textContent = '조회 실패';
      return;
    }

    if (s.service_running) {
      svcBadge.className = 'badge badge-success gap-1 text-xs py-2 px-2.5';
      svcBadge.innerHTML = '<span class="size-1.5 rounded-full bg-current animate-pulse"></span>구동 중';
    } else {
      svcBadge.className = 'badge badge-error gap-1 text-xs py-2 px-2.5';
      svcBadge.innerHTML = '<span class="size-1.5 rounded-full bg-current animate-ping"></span>정지됨';
    }

    // 서비스는 살아 있는데 serverinfo(47989)가 안 나오면 기동 직후이거나 응답 불능 상태
    if (s.stream_state === 'BUSY') {
      streamBadge.className = 'badge badge-warning badge-sm';
      streamBadge.textContent = 'BUSY (세션 있음)';
    } else if (s.stream_state === 'FREE') {
      streamBadge.className = 'badge badge-success badge-sm';
      streamBadge.textContent = 'FREE (대기)';
    } else {
      streamBadge.className = 'badge badge-ghost badge-sm';
      streamBadge.textContent = s.api_reachable ? '-' : '응답 없음';
    }

    const app = s.current_app_id
      ? (s.current_app_name ? s.current_app_name + ' (' + s.current_app_id + ')' : 'ID ' + s.current_app_id)
      : '없음';
    el('current-app').textContent = app;
    el('host-name').textContent = s.host_name || '-';
    el('public-host').textContent = s.public_host || '-';

    el('session-close').disabled = s.stream_state !== 'BUSY';
    el('cred-warning').hidden = !!s.credentials_configured;
  }

  /* ---------- 2. 서비스 제어 / 세션 종료 ---------- */
  async function controlService(action) {
    const msg = { start: '서비스 시작 신호 전송 중...', stop: '서비스 중지 신호 전송 중...', restart: '서비스 재시작 중...' };
    showToast(msg[action] || '처리 중...', 'info');
    setControlDisabled(true);
    try {
      const resp = await apiFetch(API + '/control/' + action, { method: 'POST', body: JSON.stringify({}) });
      const data = await resp.json();
      if (!resp.ok) throw new Error(data.error || '제어 실패');
      showToast(data.summary || '처리했습니다.', 'success');
    } catch (e) {
      showToast('Sunshine 서비스 제어 실패: ' + escapeHtml(e.message), 'error');
    } finally {
      setControlDisabled(false);
      // Restart-Service 직후 serverinfo 가 뜨기까지 수 초 걸린다
      setTimeout(loadStatus, 1500);
      setTimeout(loadStatus, 5000);
    }
  }

  async function closeSession() {
    el('session-close-modal').close();
    try {
      const resp = await apiFetch(API + '/session/close', { method: 'POST', body: JSON.stringify({}) });
      const data = await resp.json();
      if (!resp.ok) throw new Error(data.error || '세션 종료 실패');
      showToast(data.summary || '세션을 종료했습니다.', 'success');
    } catch (e) {
      showToast('세션 종료 실패: ' + escapeHtml(e.message), 'error');
    } finally {
      setTimeout(loadStatus, 1000);
    }
  }

  function setControlDisabled(disabled) {
    ['svc-start', 'svc-stop', 'svc-restart'].forEach(function (id) { el(id).disabled = disabled; });
  }

  /* ---------- 3. PIN 페어링 ---------- */
  async function submitPin(ev) {
    ev.preventDefault();
    const pin = el('pin-input').value.trim();
    const name = el('pin-name').value.trim();
    if (!/^\d{4}$/.test(pin)) { showToast('PIN 은 숫자 4자리여야 합니다.', 'warning'); return; }
    if (!name) { showToast('기기 이름을 입력하세요.', 'warning'); return; }

    el('pin-submit').disabled = true;
    try {
      const resp = await apiFetch(API + '/pin', { method: 'POST', body: JSON.stringify({ pin: pin, name: name }) });
      const data = await resp.json();
      if (!resp.ok) throw new Error(data.error || '페어링 실패');
      showToast(data.summary || '페어링을 승인했습니다.', 'success');
      el('pin-input').value = '';
      loadClients();
    } catch (e) {
      showToast('페어링 승인 실패: ' + escapeHtml(e.message), 'error');
    } finally {
      el('pin-submit').disabled = false;
    }
  }

  /* ---------- 4. 페어링된 기기 ---------- */
  async function loadClients() {
    const body = el('clients-body');
    try {
      const resp = await apiFetch(API + '/clients?t=' + Date.now());
      const data = await resp.json();
      if (!resp.ok) throw new Error(data.error || '목록 조회 실패');
      renderClients(data.clients || []);
    } catch (e) {
      el('clients-count').textContent = '-';
      body.innerHTML = '<tr><td colspan="3" class="text-center py-4 text-xs text-error">기기 목록 조회 실패: '
        + escapeHtml(e.message) + '</td></tr>';
    }
  }

  function renderClients(clients) {
    const body = el('clients-body');
    el('clients-count').textContent = clients.length;
    if (!clients.length) {
      body.innerHTML = '<tr><td colspan="3" class="text-center py-4 text-xs opacity-50">페어링된 기기가 없습니다.</td></tr>';
      return;
    }
    body.innerHTML = clients.map(function (c) {
      return '<tr>'
        + '<td class="font-semibold text-xs">' + escapeHtml(c.name || '(이름 없음)') + '</td>'
        + '<td class="font-mono text-xs opacity-70 break-all">' + escapeHtml(c.uuid) + '</td>'
        + '<td class="text-center"><button class="btn btn-ghost btn-xs text-error btn-unpair" data-uuid="'
        + escapeHtml(c.uuid) + '" data-name="' + escapeHtml(c.name || '') + '">'
        + '<i data-lucide="unlink" class="size-3.5"></i>해제</button></td>'
        + '</tr>';
    }).join('');
    body.querySelectorAll('.btn-unpair').forEach(function (btn) {
      btn.addEventListener('click', function () {
        pendingUnpair = { uuid: btn.dataset.uuid, name: btn.dataset.name };
        el('unpair-target').textContent = (pendingUnpair.name || '(이름 없음)') + ' [' + pendingUnpair.uuid + ']';
        el('unpair-modal').showModal();
      });
    });
    if (window.lucide) lucide.createIcons();
  }

  async function confirmUnpair() {
    const target = pendingUnpair;
    el('unpair-modal').close();
    if (!target) return;
    try {
      const resp = await apiFetch(API + '/clients/unpair', { method: 'POST', body: JSON.stringify(target) });
      const data = await resp.json();
      if (!resp.ok) throw new Error(data.error || '해제 실패');
      showToast(data.summary || '페어링을 해제했습니다.', 'success');
    } catch (e) {
      showToast('페어링 해제 실패: ' + escapeHtml(e.message), 'error');
    } finally {
      pendingUnpair = null;
      loadClients();
    }
  }

  /* ---------- 5. 로그 ---------- */
  async function loadLogs() {
    const box = el('log-container');
    try {
      const resp = await apiFetch(API + '/logs?lines=200&t=' + Date.now());
      const data = await resp.json();
      if (!resp.ok) throw new Error(data.error || '로그 조회 실패');
      if (!data.logs || !data.logs.length) {
        box.innerHTML = '<div class="opacity-50 text-center py-10">출력할 로그가 없습니다.</div>';
        return;
      }
      const atBottom = (box.scrollHeight - box.scrollTop - box.clientHeight) < 35;
      box.innerHTML = data.logs.map(function (line) {
        let cls = 'opacity-80';
        if (/Error:|Fatal:/.test(line)) cls = 'text-error font-semibold';
        else if (/Warning:/.test(line)) cls = 'text-warning';
        else if (/CLIENT CONNECTED|CLIENT DISCONNECTED|pair/i.test(line)) cls = 'text-info/80';
        return '<div class="leading-relaxed ' + cls + '">' + escapeHtml(line) + '</div>';
      }).join('');
      if (atBottom) box.scrollTop = box.scrollHeight;
    } catch (e) {
      box.innerHTML = '<div class="text-error text-center py-10">Sunshine 로그 조회 실패: ' + escapeHtml(e.message) + '</div>';
    }
  }

  /* ---------- 초기화 ---------- */
  document.addEventListener('DOMContentLoaded', function () {
    loadStatus();
    loadClients();
    loadLogs();

    setInterval(loadStatus, 5000);
    setInterval(function () {
      if (el('log-auto').checked && !document.hidden) loadLogs();
    }, 5000);

    el('svc-start').addEventListener('click', function () { controlService('start'); });
    el('svc-stop').addEventListener('click', function () { controlService('stop'); });
    el('svc-restart').addEventListener('click', function () { controlService('restart'); });
    el('session-close').addEventListener('click', function () { el('session-close-modal').showModal(); });
    el('session-close-confirm').addEventListener('click', closeSession);
    el('pin-form').addEventListener('submit', submitPin);
    el('clients-refresh').addEventListener('click', loadClients);
    el('unpair-confirm').addEventListener('click', confirmUnpair);
    el('log-refresh').addEventListener('click', loadLogs);
  });
})();
