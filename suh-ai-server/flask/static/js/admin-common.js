/* API Key 관리 + 인증 fetch 래퍼. nginx가 X-API-Key를 검증한다. */
(function () {
  const KEY_STORAGE = 'suh_admin_api_key';

  function getApiKey() {
    return localStorage.getItem(KEY_STORAGE) || '';
  }

  function showKeyModal() {
    document.getElementById('api-key-modal').showModal();
  }

  window.saveApiKey = function () {
    const input = document.getElementById('api-key-input');
    if (input.value.trim()) {
      localStorage.setItem(KEY_STORAGE, input.value.trim());
      document.getElementById('api-key-modal').close();
      window.location.reload();
    }
  };

  window.resetApiKey = function () {
    localStorage.removeItem(KEY_STORAGE);
    showKeyModal();
  };

  /* 상대경로 전용 fetch — 401이면 키 재입력 modal */
  window.apiFetch = async function (path, options = {}) {
    const headers = Object.assign({}, options.headers, {
      'X-API-Key': getApiKey(),
      'Content-Type': 'application/json',
    });
    const resp = await fetch(path, Object.assign({}, options, { headers }));
    if (resp.status === 401) {
      showKeyModal();
      throw new Error('Unauthorized - API Key required');
    }
    return resp;
  };

  window.escapeHtml = function (value) {
    return String(value).replace(/[&<>"']/g, function (ch) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[ch];
    });
  };

  window.showToast = function (message, type = 'info') {
    const toast = document.getElementById('toast-container');
    const alert = document.createElement('div');
    alert.className = 'alert alert-' + type;
    alert.innerHTML = '<span>' + message + '</span>';
    toast.appendChild(alert);
    setTimeout(() => alert.remove(), 4000);
  };

  document.addEventListener('DOMContentLoaded', function () {
    if (!getApiKey()) showKeyModal();
  });
})();
