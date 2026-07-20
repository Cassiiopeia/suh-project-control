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

  /* 메트릭 히스토리 스파크라인 (외부 라이브러리 없이 인라인 SVG) — 대시보드·팰월드 공용 */
  window.sparkline = function (container, values, opts) {
    opts = opts || {};
    const el = typeof container === 'string' ? document.getElementById(container) : container;
    if (!el) return;
    const nums = values.filter(v => typeof v === 'number' && !isNaN(v));
    if (nums.length < 2) { el.innerHTML = '<div class="text-xs opacity-40 pt-4">데이터 수집 중…</div>'; return; }
    const W = 300, H = 48, pad = 2;
    const min = opts.min != null ? opts.min : Math.min.apply(null, nums);
    const max = opts.max != null ? opts.max : Math.max.apply(null, nums);
    const span = (max - min) || 1;
    const stepX = (W - pad * 2) / (values.length - 1);
    const pts = values.map((v, i) => {
      const y = (typeof v === 'number' && !isNaN(v))
        ? H - pad - ((v - min) / span) * (H - pad * 2) : null;
      return { x: pad + i * stepX, y: y };
    }).filter(p => p.y != null);
    const line = pts.map((p, i) => (i ? 'L' : 'M') + p.x.toFixed(1) + ' ' + p.y.toFixed(1)).join(' ');
    const area = line + ' L' + pts[pts.length - 1].x.toFixed(1) + ' ' + H + ' L' + pts[0].x.toFixed(1) + ' ' + H + ' Z';
    const color = opts.color || 'currentColor';
    el.innerHTML =
      '<svg viewBox="0 0 ' + W + ' ' + H + '" preserveAspectRatio="none" class="w-full h-full ' + (opts.klass || 'text-primary') + '">' +
      '<path d="' + area + '" fill="' + color + '" opacity="0.12"/>' +
      '<path d="' + line + '" fill="none" stroke="' + color + '" stroke-width="1.5" vector-effect="non-scaling-stroke"/>' +
      '</svg>';
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
