/* AI 서버 공용 PG 관리 화면. API: ../ai-db/*
   흐름: 상태 > DB·계정 목록 > 만들기 / 접속 권한 주기·빼기 / 비번 재발급(1회 표시) / 이름 입력 후 삭제 > 목록 새로 고침
   gbrain: DB별 상태 > 브레인 준비(쓰기 계정) / 팀원 읽기 권한 주기·빼기 (일반 접속 권한과 섞지 않음) */
(function () {
  const API = '../ai-db';
  // 미연결 표시용 에러 코드 (설계 6장)
  const UNAVAILABLE_ERROR_CODE = 'E-AIDB-503';
  // 서버 error 코드 > 화면 문구
  const ERROR_LABELS = {
    ai_db_unavailable: 'DB 서버에 연결하지 못했어요 (' + UNAVAILABLE_ERROR_CODE + ').',
    invalid_name: '이름은 소문자로 시작하고 소문자·숫자·밑줄로 3~41자예요.',
    protected_object: '보호된 대상이라 바꿀 수 없어요.',
    permission_denied: '관리 계정 권한 밖이라 바꿀 수 없어요.',
    confirm_mismatch: '입력한 이름이 달라요.',
    not_found: '대상을 찾지 못했어요. 목록을 새로 고칠게요.',
    already_exists: '같은 이름이 이미 있어요.',
    database_in_use: '접속 중인 연결이 있어 지울 수 없어요. 연결을 끊고 다시 시도하세요.',
    role_in_use: '권한이나 객체가 남아 있어요. DB 접속 권한을 먼저 빼 주세요.',
    bad_request: '요청 형식이 잘못됐어요.',
    gbrain_ops_missing: '이 DB에 관리 함수가 없어요. 슈퍼유저로 sql/ai_db_ops_gbrain.sql 을 먼저 실행하세요.',
    same_reader_writer: '쓰기 계정은 읽기 팀원으로 줄 수 없어요.',
  };
  const BYTES_PER_MEGABYTE = 1024 * 1024;

  let databases = [];
  let roles = [];
  // 삭제 확인 대상 { kind: 'database' | 'role', name }
  let pendingDelete = null;
  let grantDatabaseName = null;
  // DB 이름 > gbrain 상태 { is_ready, has_ops_functions, has_pages_table, writer_role, readers }
  let gbrainByDatabase = {};
  // gbrain 모달 대상 { mode: 'prepare' | 'reader', databaseName }
  let pendingGbrain = null;

  function el(id) { return document.getElementById(id); }
  const escapeHtml = window.escapeHtml;

  function describeError(errorCode) {
    return ERROR_LABELS[errorCode] || ('요청에 실패했어요 (' + escapeHtml(errorCode || 'unknown') + ').');
  }

  async function requestJson(path, options) {
    const response = await apiFetch(API + path, options || {});
    const responseBody = await response.json().catch(() => ({}));
    return { isOk: response.ok, body: responseBody };
  }

  /* ---------- 1. 상태·목록 ---------- */
  async function loadAll() {
    await loadStatus();
    await Promise.all([loadDatabases(), loadRoles()]);
  }

  async function loadStatus() {
    const status = el('ai-db-status');
    try {
      const result = await requestJson('/status');
      const address = escapeHtml((result.body.public_host || '') + ':' + (result.body.public_port || ''));
      status.innerHTML = result.isOk
        ? '<span class="badge badge-success badge-xs"></span><span>연결됨 · PostgreSQL ' +
          escapeHtml(result.body.server_version || '') + ' · <span class="font-mono">' + address + '</span></span>'
        : '<span class="badge badge-error badge-xs"></span><span>연결 안 됨 (' + UNAVAILABLE_ERROR_CODE + ')</span>';
    } catch (error) {
      console.warn('ai db status failed:', error);
      status.innerHTML = '<span class="badge badge-error badge-xs"></span><span>연결 안 됨 (' + UNAVAILABLE_ERROR_CODE + ')</span>';
    }
  }

  async function loadDatabases() {
    const result = await requestJson('/databases').catch(() => ({ isOk: false, body: {} }));
    if (!result.isOk) {
      el('database-list').innerHTML = '<p class="text-sm opacity-60">' + describeError(result.body.error || 'ai_db_unavailable') + '</p>';
      return;
    }
    databases = result.body.databases || [];
    renderDatabases();
    await loadGbrainStatuses();
  }

  // 보호 DB 제외 DB별 gbrain 상태 (실패한 DB는 섹션에 오류 표시)
  async function loadGbrainStatuses() {
    const entries = await Promise.all(databases.filter(d => !d.is_protected).map(async function (database) {
      const result = await requestJson('/databases/' + encodeURIComponent(database.name) + '/gbrain')
        .catch(() => ({ isOk: false, body: {} }));
      return [database.name, result.isOk ? result.body : { error: result.body.error || 'ai_db_unavailable' }];
    }));
    gbrainByDatabase = Object.fromEntries(entries);
    renderDatabases();
  }

  function gbrainReadersOf(databaseName) {
    const gbrain = gbrainByDatabase[databaseName];
    return (gbrain && gbrain.readers) || [];
  }

  async function loadRoles() {
    const result = await requestJson('/roles').catch(() => ({ isOk: false, body: {} }));
    if (!result.isOk) {
      el('role-rows').innerHTML = '<tr><td colspan="2" class="opacity-60">' + describeError(result.body.error || 'ai_db_unavailable') + '</td></tr>';
      return;
    }
    roles = result.body.roles || [];
    renderRoles();
  }

  function formatSize(sizeBytes) {
    if (sizeBytes == null) return '-';
    return (sizeBytes / BYTES_PER_MEGABYTE).toFixed(1) + 'MB';
  }

  function renderDatabases() {
    el('database-list').innerHTML = databases.length ? databases.map(renderDatabaseItem).join('')
      : '<p class="text-sm opacity-60">DB가 없어요. DB 만들기를 누르세요.</p>';
    if (window.lucide) lucide.createIcons();
  }

  function renderDatabaseItem(database) {
    const name = escapeHtml(database.name);
    const isProtected = database.is_protected;
    // 읽기 팀원은 gbrain 섹션에서만 표시·회수 (일반 회수는 읽기 권한을 반쯤 남김)
    const readers = gbrainReadersOf(database.name);
    const accessBadges = (database.access_roles || []).filter(roleName => readers.indexOf(roleName) < 0).map(function (roleName) {
      const removeButton = isProtected ? '' : '<button class="btn btn-ghost btn-xs px-1" data-action="revoke" data-role="' +
        escapeHtml(roleName) + '" aria-label="권한 빼기"><i data-lucide="x" class="size-3"></i></button>';
      return '<span class="badge badge-outline gap-1 font-mono">' + escapeHtml(roleName) + removeButton + '</span>';
    }).join(' ') || '<span class="opacity-60">없음</span>';
    const actions = isProtected ? '<span class="badge badge-ghost badge-sm gap-1"><i data-lucide="lock" class="size-3"></i>보호됨</span>'
      : '<button class="btn btn-ghost btn-xs" data-action="grant"><i data-lucide="plus" class="size-3"></i>권한</button>' +
        '<button class="btn btn-ghost btn-xs text-error" data-action="delete" aria-label="삭제"><i data-lucide="trash-2" class="size-3"></i></button>';
    return '<div class="border border-base-300 rounded-box p-3" data-database="' + name + '">' +
      '<div class="flex flex-wrap items-center justify-between gap-2">' +
        '<div><span class="font-mono font-bold">' + name + '</span> <span class="text-xs opacity-70">' +
          formatSize(database.size_bytes) + ' · 소유 ' + escapeHtml(database.owner || '-') + '</span></div>' +
        '<div class="whitespace-nowrap">' + actions + '</div>' +
      '</div>' +
      '<div class="text-xs mt-2 flex flex-wrap items-center gap-1"><span class="opacity-70">접속 가능:</span>' + accessBadges + '</div>' +
      (isProtected ? '' : renderGbrainSection(database.name)) +
    '</div>';
  }

  // gbrain 섹션: 상태 배지 · 쓰기 계정 · 읽기 팀원(빼기) · 준비 / 읽기 권한 주기
  function renderGbrainSection(databaseName) {
    const gbrain = gbrainByDatabase[databaseName];
    const header = '<span class="flex items-center gap-1 opacity-70"><i data-lucide="brain" class="size-3"></i>gbrain</span>';
    if (!gbrain) return '<div class="text-xs mt-2 pt-2 border-t border-base-300 flex items-center gap-2">' + header + '<span class="opacity-60">확인 중</span></div>';
    if (gbrain.error) return '<div class="text-xs mt-2 pt-2 border-t border-base-300 flex items-center gap-2">' + header + '<span class="text-error">' + describeError(gbrain.error) + '</span></div>';
    const statusBadge = gbrain.is_ready ? '<span class="badge badge-success badge-xs">준비됨</span>' : '<span class="badge badge-warning badge-xs">미준비</span>';
    const opsHint = gbrain.has_ops_functions ? '' : '<span class="text-warning">관리 함수 없음 (sql/ai_db_ops_gbrain.sql)</span>';
    const prepareButton = '<button class="btn btn-ghost btn-xs" data-action="gbrain-prepare"><i data-lucide="sparkles" class="size-3"></i>브레인 준비</button>';
    if (!gbrain.is_ready || !gbrain.writer_role) {
      return '<div class="text-xs mt-2 pt-2 border-t border-base-300 flex flex-wrap items-center gap-2">' + header + statusBadge + opsHint + prepareButton + '</div>';
    }
    const readerBadges = (gbrain.readers || []).map(function (roleName) {
      return '<span class="badge badge-outline gap-1 font-mono">' + escapeHtml(roleName) +
        '<button class="btn btn-ghost btn-xs px-1" data-action="gbrain-revoke-reader" data-role="' + escapeHtml(roleName) +
        '" aria-label="읽기 권한 빼기"><i data-lucide="x" class="size-3"></i></button></span>';
    }).join(' ') || '<span class="opacity-60">없음</span>';
    return '<div class="text-xs mt-2 pt-2 border-t border-base-300 space-y-1">' +
      '<div class="flex flex-wrap items-center gap-2">' + header + statusBadge +
        '<span class="opacity-70">쓰기</span><span class="font-mono">' + escapeHtml(gbrain.writer_role) + '</span>' +
        '<button class="btn btn-ghost btn-xs" data-action="gbrain-grant-reader"><i data-lucide="user-plus" class="size-3"></i>팀원 읽기 권한 주기</button></div>' +
      '<div class="flex flex-wrap items-center gap-1"><span class="opacity-70">읽기 팀원:</span>' + readerBadges + '</div>' +
    '</div>';
  }

  function renderRoles() {
    el('role-rows').innerHTML = roles.length ? roles.map(renderRoleRow).join('')
      : '<tr><td colspan="2" class="opacity-60">계정이 없어요. 계정 만들기를 누르세요.</td></tr>';
    if (window.lucide) lucide.createIcons();
  }

  function renderRoleRow(role) {
    const actions = role.is_protected ? '<span class="badge badge-ghost badge-sm gap-1"><i data-lucide="lock" class="size-3"></i>보호됨</span>'
      : '<button class="btn btn-ghost btn-xs" data-action="reset-password"><i data-lucide="key-round" class="size-3"></i>비번 재발급</button>' +
        '<button class="btn btn-ghost btn-xs text-error" data-action="delete" aria-label="삭제"><i data-lucide="trash-2" class="size-3"></i></button>';
    return '<tr data-role="' + escapeHtml(role.name) + '"><td class="font-mono font-bold">' + escapeHtml(role.name) + '</td>' +
      '<td class="text-right whitespace-nowrap">' + actions + '</td></tr>';
  }

  /* ---------- 2. 선택지 채우기 (보호 대상 제외) ---------- */
  function fillSelect(select, names, emptyLabel) {
    select.innerHTML = (emptyLabel != null ? '<option value="">' + escapeHtml(emptyLabel) + '</option>' : '') +
      names.map(function (name) { return '<option value="' + escapeHtml(name) + '">' + escapeHtml(name) + '</option>'; }).join('');
  }

  function manageableRoleNames() { return roles.filter(r => !r.is_protected).map(r => r.name); }
  function manageableDatabaseNames() { return databases.filter(d => !d.is_protected).map(d => d.name); }

  function showFormError(id, errorCode) {
    el(id).textContent = describeError(errorCode);
    el(id).hidden = false;
  }

  function openModal(id) {
    el(id).querySelectorAll('.text-error[id$="-form-error"]').forEach(node => { node.hidden = true; });
    el(id).showModal();
  }

  /* ---------- 3. 만들기 ---------- */
  async function onDatabaseSubmit(event) {
    event.preventDefault();
    const result = await requestJson('/databases', { method: 'POST', body: JSON.stringify({
      name: el('database-name').value.trim(), owner_role: el('database-owner-role').value || null }) });
    if (!result.isOk) return showFormError('database-form-error', result.body.error);
    el('database-modal').close();
    showToast('DB를 만들었어요', 'success');
    loadAll();
  }

  async function onRoleSubmit(event) {
    event.preventDefault();
    const result = await requestJson('/roles', { method: 'POST', body: JSON.stringify({
      name: el('role-name').value.trim(), database: el('role-database').value || null }) });
    if (!result.isOk) return showFormError('role-form-error', result.body.error);
    el('role-modal').close();
    showSecret('계정을 만들었어요', result.body);
    loadAll();
  }

  /* ---------- 4. 비번·연결 문자열 1회 표시 (닫으면 지움) ---------- */
  function showSecret(title, secret) {
    el('secret-title').textContent = title;
    el('secret-password').value = secret.password || '';
    el('secret-connection-url').value = secret.connection_url || '';
    el('secret-database-hint').hidden = Boolean(secret.database);
    el('secret-modal').showModal();
  }

  function clearSecret() {
    el('secret-password').value = '';
    el('secret-connection-url').value = '';
  }

  // 클립보드 복사 (clipboard API 없으면 입력칸 선택 > execCommand)
  async function copyInputValue(input) {
    try {
      if (navigator.clipboard && window.isSecureContext) {
        await navigator.clipboard.writeText(input.value);
      } else {
        input.select();
        document.execCommand('copy');
      }
      showToast('복사했어요', 'success');
    } catch (error) {
      console.warn('ai db copy failed:', error);
      showToast('복사하지 못했어요. 직접 선택해 복사하세요', 'error');
    }
  }

  /* ---------- 5. 목록 버튼 (권한 주기·빼기 · 비번 재발급 · 삭제) ---------- */
  async function onDatabaseListClick(event) {
    const button = event.target.closest('button[data-action]');
    if (!button) return;
    const databaseName = button.closest('[data-database]').dataset.database;
    if (button.dataset.action === 'grant') {
      grantDatabaseName = databaseName;
      el('grant-database').textContent = databaseName;
      // gbrain 읽기 팀원 제외 (일반 권한은 public 스키마 CREATE 까지 줘서 읽기 전용이 깨짐)
      fillSelect(el('grant-role'), manageableRoleNames().filter(roleName => gbrainReadersOf(databaseName).indexOf(roleName) < 0));
      openModal('grant-modal');
    } else if (button.dataset.action === 'revoke') {
      const roleName = button.dataset.role;
      const result = await requestJson('/databases/' + encodeURIComponent(databaseName) + '/grants/' + encodeURIComponent(roleName), { method: 'DELETE' });
      showToast(result.isOk ? '접속 권한을 뺐어요' : describeError(result.body.error), result.isOk ? 'success' : 'error');
      loadDatabases();
    } else if (button.dataset.action === 'delete') {
      openDelete('database', databaseName);
    } else if (button.dataset.action === 'gbrain-prepare') {
      openGbrainModal('prepare', databaseName);
    } else if (button.dataset.action === 'gbrain-grant-reader') {
      openGbrainModal('reader', databaseName);
    } else if (button.dataset.action === 'gbrain-revoke-reader') {
      const result = await requestJson(gbrainReaderPath(databaseName, button.dataset.role), { method: 'DELETE',
        body: JSON.stringify({ writer_role: gbrainByDatabase[databaseName].writer_role }) });
      showToast(result.isOk ? '읽기 권한을 뺐어요' : describeError(result.body.error), result.isOk ? 'success' : 'error');
      loadDatabases();
    }
  }

  /* ---------- 5-1. gbrain (준비: DB 접속 계정 중 쓰기 계정 / 읽기: 일반 접속 권한 없는 계정만) ---------- */
  function gbrainReaderPath(databaseName, roleName) {
    return '/databases/' + encodeURIComponent(databaseName) + '/gbrain/readers/' + encodeURIComponent(roleName);
  }

  function openGbrainModal(mode, databaseName) {
    const database = databases.find(d => d.name === databaseName) || {};
    const gbrain = gbrainByDatabase[databaseName] || {};
    const readers = gbrain.readers || [];
    // 일반 접속 권한 계정 = public 스키마 CREATE 보유 > 읽기 팀원 후보에서 제외
    const generalAccessRoles = (database.access_roles || []).filter(roleName => readers.indexOf(roleName) < 0);
    const isPrepare = mode === 'prepare';
    const candidates = isPrepare ? generalAccessRoles.filter(roleName => manageableRoleNames().indexOf(roleName) >= 0)
      : manageableRoleNames().filter(roleName => generalAccessRoles.indexOf(roleName) < 0 && readers.indexOf(roleName) < 0);
    pendingGbrain = { mode: mode, databaseName: databaseName };
    el('gbrain-title').textContent = isPrepare ? '브레인 준비' : '팀원 읽기 권한 주기';
    el('gbrain-database').textContent = databaseName;
    el('gbrain-description').textContent = isPrepare ? '에 동기화할 쓰기 계정을 골라요.' : '을 읽기만 할 팀원 계정을 골라요.';
    el('gbrain-hint').textContent = isPrepare
      ? '확장·RLS 자동 설정을 하고 쓰기 계정이 모든 행을 다룰 수 있게 해요. 후보가 없으면 먼저 접속 권한을 주세요.'
      : '계정은 DB를 고르지 않고 만든 뒤 여기서 주세요. 일반 접속 권한(쓰기 가능)이 있는 계정은 고를 수 없어요.';
    el('gbrain-submit').textContent = isPrepare ? '준비' : '읽기 권한 주기';
    fillSelect(el('gbrain-role'), candidates);
    openModal('gbrain-modal');
  }

  async function onGbrainSubmit(event) {
    event.preventDefault();
    if (!pendingGbrain) return;
    const roleName = el('gbrain-role').value;
    if (!roleName) return showFormError('gbrain-form-error', 'bad_request');
    const databaseName = pendingGbrain.databaseName;
    const isPrepare = pendingGbrain.mode === 'prepare';
    const path = isPrepare ? '/databases/' + encodeURIComponent(databaseName) + '/gbrain/prepare' : gbrainReaderPath(databaseName, roleName);
    const writerRole = isPrepare ? roleName : gbrainByDatabase[databaseName].writer_role;
    const result = await requestJson(path, { method: isPrepare ? 'POST' : 'PUT', body: JSON.stringify({ writer_role: writerRole }) });
    if (!result.isOk) return showFormError('gbrain-form-error', result.body.error);
    el('gbrain-modal').close();
    showToast(isPrepare ? '브레인을 준비했어요' : '읽기 권한을 줬어요', 'success');
    loadDatabases();
  }

  async function onGrantSubmit(event) {
    event.preventDefault();
    const roleName = el('grant-role').value;
    if (!roleName) return showFormError('grant-form-error', 'bad_request');
    const result = await requestJson('/databases/' + encodeURIComponent(grantDatabaseName) + '/grants/' + encodeURIComponent(roleName), { method: 'PUT' });
    if (!result.isOk) return showFormError('grant-form-error', result.body.error);
    el('grant-modal').close();
    showToast('접속 권한을 줬어요', 'success');
    loadDatabases();
  }

  async function onRoleRowClick(event) {
    const button = event.target.closest('button[data-action]');
    if (!button) return;
    const roleName = button.closest('[data-role]').dataset.role;
    if (button.dataset.action === 'delete') return openDelete('role', roleName);
    // 비번 재발급: 접속 가능한 첫 DB를 연결 문자열에 넣음 (없으면 DB 없이)
    const accessibleDatabase = databases.find(d => (d.access_roles || []).indexOf(roleName) >= 0 && !d.is_protected);
    const result = await requestJson('/roles/' + encodeURIComponent(roleName) + '/password', { method: 'POST',
      body: JSON.stringify({ database: accessibleDatabase ? accessibleDatabase.name : null }) });
    if (!result.isOk) return showToast(describeError(result.body.error), 'error');
    showSecret('비번을 재발급했어요', result.body);
  }

  /* ---------- 6. 삭제 (이름 입력 일치 시에만 버튼 활성) ---------- */
  function openDelete(kind, name) {
    pendingDelete = { kind: kind, name: name };
    el('delete-title').textContent = kind === 'database' ? 'DB 삭제' : '계정 삭제';
    el('delete-target').textContent = name;
    el('delete-confirm-name').value = '';
    el('delete-submit').disabled = true;
    openModal('delete-modal');
  }

  async function onDeleteSubmit(event) {
    event.preventDefault();
    if (!pendingDelete) return;
    const path = (pendingDelete.kind === 'database' ? '/databases/' : '/roles/') + encodeURIComponent(pendingDelete.name);
    const result = await requestJson(path, { method: 'DELETE', body: JSON.stringify({ confirm_name: el('delete-confirm-name').value }) });
    if (!result.isOk) return showFormError('delete-form-error', result.body.error);
    el('delete-modal').close();
    showToast('삭제했어요', 'success');
    loadAll();
  }

  /* ---------- 7. 연결 ---------- */
  function openCreateModal(modalId, inputId, selectId, names, emptyLabel) {
    el(inputId).value = '';
    fillSelect(el(selectId), names, emptyLabel);
    openModal(modalId);
  }

  document.addEventListener('DOMContentLoaded', function () {
    el('ai-db-refresh').addEventListener('click', loadAll);
    el('database-add').addEventListener('click', () => openCreateModal('database-modal', 'database-name', 'database-owner-role', manageableRoleNames(), '나중에 줄게요'));
    el('role-add').addEventListener('click', () => openCreateModal('role-modal', 'role-name', 'role-database', manageableDatabaseNames(), '나중에 고를게요'));
    el('database-form').addEventListener('submit', onDatabaseSubmit);
    el('role-form').addEventListener('submit', onRoleSubmit);
    el('grant-form').addEventListener('submit', onGrantSubmit);
    el('gbrain-form').addEventListener('submit', onGbrainSubmit);
    el('delete-form').addEventListener('submit', onDeleteSubmit);
    el('database-list').addEventListener('click', onDatabaseListClick);
    el('role-rows').addEventListener('click', onRoleRowClick);
    el('delete-confirm-name').addEventListener('input', function () {
      el('delete-submit').disabled = !pendingDelete || this.value !== pendingDelete.name;
    });
    el('secret-modal').addEventListener('close', clearSecret);
    document.querySelectorAll('[data-close-modal]').forEach(button => {
      button.addEventListener('click', () => button.closest('dialog').close());
    });
    document.querySelectorAll('[data-copy-target]').forEach(button => {
      button.addEventListener('click', () => copyInputValue(el(button.dataset.copyTarget)));
    });
    loadAll();
  });
})();
