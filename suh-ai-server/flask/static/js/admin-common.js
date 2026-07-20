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

  /* ---------- 5. 공통 모델 패밀리 및 필터 처리 유틸리티 ---------- */
  window.getActualFamily = function (m) {
    if (!m || !m.name) return 'unknown';
    let name = m.name.toLowerCase();
    
    // hf.co 경로 정제
    if (name.indexOf('hf.co/') === 0) {
      const parts = name.split('/');
      if (parts.length > 2) {
        name = parts.slice(2).join('/');
      } else {
        name = parts[1] || name;
      }
    }
    
    // ':' 뒤의 태그 제거
    if (name.includes(':')) {
      name = name.split(':')[0];
    }
    
    // 아키텍처 정밀 키워드 매핑
    if (name.includes('gemma3n')) return 'gemma3n';
    if (name.includes('gemma3') || name.includes('gemma-3')) return 'gemma3';
    if (name.includes('gemma4') || name.includes('gemma-4')) return 'gemma4';
    if (name.includes('deepseek-ocr')) return 'deepseek-ocr';
    if (name.includes('deepseek-r1') || name.includes('deepseek-r-1')) return 'deepseek-r1';
    if (name.includes('embeddinggemma')) return 'embeddinggemma';
    if (name.includes('exaone-deep')) return 'exaone-deep';
    if (name.includes('functiongemma')) return 'functiongemma';
    if (name.includes('glm-ocr') || name.includes('glmocr')) return 'glm-ocr';
    if (name.includes('granite4') || name.includes('granite-4')) return 'granite4';
    if (name.includes('lfm2.5-thinking') || name.includes('lfm-2.5-thinking')) return 'lfm2.5-thinking';
    if (name.includes('minicpm-v4.6') || name.includes('minicpmv4.6')) return 'minicpm-v4.6';
    if (name.includes('ministral-3') || name.includes('ministral3')) return 'ministral-3';
    if (name.includes('qwen3-embedding') || name.includes('qwen-3-embedding')) return 'qwen3-embedding';
    if (name.includes('qwen3-vl') || name.includes('qwen-3-vl')) return 'qwen3-vl';
    if (name.includes('qwen3.5') || name.includes('qwen-3.5')) return 'qwen3.5';
    if (name.includes('qwen3') || name.includes('qwen-3')) return 'qwen3';
    if (name.includes('rnj-1')) return 'rnj-1';
    if (name.includes('hyperclovax') || name.includes('hyper-clova')) return 'hyperclovax';
    if (name.includes('kanana')) return 'kanana';
    if (name.includes('llava')) return 'llava';
    
    // 백엔드 family 폴백
    if (m.family) {
      const famLower = m.family.toLowerCase();
      if (famLower.includes('gemma3')) return 'gemma3';
      if (famLower.includes('gemma4')) return 'gemma4';
      if (famLower.includes('qwen2')) return 'qwen';
      return famLower;
    }
    
    // 단순 파싱 폴백
    const baseName = m.name.split(':')[0];
    if (baseName.includes('/')) {
      const slashParts = baseName.split('/');
      return slashParts[slashParts.length - 1].split('-')[0];
    }
    return baseName.split('-')[0];
  };

  window.parseParameterSize = function (paramStr) {
    if (!paramStr) return 0;
    const str = String(paramStr).toUpperCase();
    if (str.endsWith('B')) {
      return parseFloat(str.slice(0, -1)) || 0;
    }
    if (str.endsWith('M')) {
      return (parseFloat(str.slice(0, -1)) || 0) / 1000;
    }
    return parseFloat(str) || 0;
  };

  window.filterModelList = function (models, filters) {
    if (!models || !Array.isArray(models)) return [];
    
    const query = (filters.query || '').trim().toLowerCase();
    const params = filters.params || 'all';
    const maxSizeStep = filters.maxSizeStep !== undefined ? parseInt(filters.maxSizeStep) : 6;
    const capability = filters.capability || 'all';
    const source = filters.source || 'all';

    // 슬라이더 바 스텝에 따른 최대 바이트 제한 계산
    const sizeLimits = [
      0.5 * 1024 * 1024 * 1024, // 0: 0.5GB 이하
      1.0 * 1024 * 1024 * 1024, // 1: 1.0GB 이하
      4.0 * 1024 * 1024 * 1024, // 2: 4.0GB 이하
      8.0 * 1024 * 1024 * 1024, // 3: 8.0GB 이하
      12.0 * 1024 * 1024 * 1024, // 4: 12.0GB 이하
      16.0 * 1024 * 1024 * 1024, // 5: 16.0GB 이하
      Infinity                  // 6: 전체 (제한 없음)
    ];
    const maxSizeBytes = sizeLimits[maxSizeStep] || Infinity;

    return models.filter(function (m) {
      const mName = m.name.toLowerCase();
      const actualFamily = window.getActualFamily(m);

      // 1. 텍스트 검색 필터 (이름 또는 매핑된 실제 패밀리명)
      if (query && !mName.includes(query) && !actualFamily.includes(query)) {
        return false;
      }

      // 2. 파라미터 크기 필터
      if (params !== 'all') {
        const val = window.parseParameterSize(m.parameter_size);
        if (params === 'under_1b' && val >= 1.0) return false;
        if (params === '1b_4b' && (val < 1.0 || val >= 4.0)) return false;
        if (params === '4b_8b' && (val < 4.0 || val >= 8.0)) return false;
        if (params === 'over_8b' && val < 8.0) return false;
      }

      // 3. 파일 용량 상한 필터
      if (m.size && m.size > maxSizeBytes) {
        return false;
      }

      // 4. 모델 유형 필터 (Vision/OCR, Embedding, General Text)
      if (capability !== 'all') {
        const isVision = !!m.vision || mName.includes('vision') || mName.includes('-vl') || mName.includes('ocr');
        const isEmbedding = m.family === 'bert' || mName.includes('embedding');
        
        if (capability === 'vision' && !isVision) return false;
        if (capability === 'embedding' && !isEmbedding) return false;
        if (capability === 'text' && (isVision || isEmbedding)) return false;
      }

      // 5. 출처 필터 (Ollama 공식 vs hf.co)
      if (source !== 'all') {
        const isHf = mName.indexOf('hf.co/') === 0;
        if (source === 'hf' && !isHf) return false;
        if (source === 'ollama' && isHf) return false;
      }

      return true;
    });
  };

  document.addEventListener('DOMContentLoaded', function () {
    if (!getApiKey()) showKeyModal();
  });
})();
