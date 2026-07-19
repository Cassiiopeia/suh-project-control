"""
Model Management Service
HF 허브 검색·GGUF 파일 조회 + Ollama 삭제/설치 목록(vision capability 포함)
"""
import logging
import re

import requests
from ollama import Client

logger = logging.getLogger(__name__)

HF_API_BASE = 'https://huggingface.co/api'
OLLAMA_SITE_BASE = 'https://ollama.com'

# ollama.com은 브라우저 UA가 없으면 요청을 차단할 수 있음
_SITE_HEADERS = {'User-Agent': 'Mozilla/5.0 (compatible; suh-ai-server)'}

# 파일명 끝의 양자화 태그 추출: gemma-3-4b-it-Q4_K_M.gguf → Q4_K_M (IQ4_XS, F16, BF16 등 포함)
_QUANT_RE = re.compile(r'[-.]((?:i?q\d[a-z0-9_]*)|f16|f32|bf16)\.gguf$', re.IGNORECASE)

# ollama.com/search 결과 파싱 — 공식 API가 없어 HTML 클래스 패턴에 의존 (구조 변경 시 결과 0건)
_OLLAMA_ITEM_RE = re.compile(r'<li\s[^>]*>(.*?)</li>', re.S)
_OLLAMA_NAME_RE = re.compile(r'href="/library/([^"/:]+)"')
_OLLAMA_DESC_RE = re.compile(r'<p class="max-w-lg break-words[^"]*">(.*?)</p>', re.S)
_OLLAMA_CAP_RE = re.compile(r'text-indigo-600[^"]*">([^<]+)</span>')      # vision·tools 등 capability 뱃지
_OLLAMA_SIZE_RE = re.compile(r'text-blue-600[^"]*">([^<]+)</span>')       # 1b·4b 등 사이즈 뱃지
_OLLAMA_PULLS_RE = re.compile(r'>([\d.,]+[KMB]?)</span>\s*<span[^>]*>&nbsp;Pulls')

# ollama.com/library/{name}/tags의 태그 행 파싱: digest • 크기 • context window
_OLLAMA_TAG_INFO_RE = re.compile(
    r'([0-9a-f]{12})</span>\s*•\s*([\d.]+\s?[KMGT]B)(?:\s*•\s*([\d.]+[KM]?) context window)?')


class ModelService:
    """HF 허브 검색과 Ollama 모델 관리(delete/list)를 담당"""

    def __init__(self, ollama_url: str = 'http://127.0.0.1:11434'):
        self.ollama_url = ollama_url.rstrip('/')
        # 명시적으로 Client를 생성하여 OLLAMA_HOST 환경변수(0.0.0.0)에 의존하지 않음
        self.client = Client(host=self.ollama_url)

    # ---------- Hugging Face ----------

    def search_hf_models(self, query: str, limit: int = 20) -> list:
        """GGUF 필터로 HF 모델 검색 — 다운로드수 내림차순

        Returns:
            [{'repo_id', 'downloads', 'likes', 'updated_at'}, ...]
        """
        resp = requests.get(
            f'{HF_API_BASE}/models',
            params={'search': query, 'filter': 'gguf', 'sort': 'downloads',
                    'direction': -1, 'limit': limit},
            timeout=15,
        )
        resp.raise_for_status()
        return [
            {
                'repo_id': m.get('id'),
                'downloads': m.get('downloads', 0),
                'likes': m.get('likes', 0),
                'updated_at': m.get('lastModified'),
            }
            for m in resp.json()
        ]

    def list_hf_gguf_files(self, repo_id: str) -> list:
        """레포의 GGUF 파일 목록 — 양자화 태그·Ollama pull용 이름 포함

        Raises:
            PermissionError: gated 모델(401/403) — 공개 모델만 지원
        """
        resp = requests.get(f'{HF_API_BASE}/models/{repo_id}/tree/main', timeout=15)
        if resp.status_code in (401, 403):
            raise PermissionError('HF 승인이 필요한 모델입니다 - 공개 모델만 지원합니다')
        resp.raise_for_status()
        files = []
        for entry in resp.json():
            path = entry.get('path', '')
            if not path.lower().endswith('.gguf'):
                continue
            match = _QUANT_RE.search(path)
            quant = match.group(1).upper() if match else None
            files.append({
                'filename': path,
                'size': entry.get('size'),
                'quant': quant,
                # 양자화 태그가 없으면 tag 없이 pull(레포의 기본 GGUF)
                'ollama_name': f'hf.co/{repo_id}:{quant}' if quant else f'hf.co/{repo_id}',
            })
        return files

    # ---------- Ollama 라이브러리 (ollama.com 파싱) ----------

    def search_ollama_models(self, query: str, limit: int = 20) -> list:
        """ollama.com/search 파싱 — 모델명·설명·pull 수·capability·사이즈

        Returns:
            [{'name', 'description', 'pulls', 'capabilities', 'sizes'}, ...]
        """
        resp = requests.get(
            f'{OLLAMA_SITE_BASE}/search',
            params={'q': query}, headers=_SITE_HEADERS, timeout=15,
        )
        resp.raise_for_status()
        results = []
        for item in _OLLAMA_ITEM_RE.findall(resp.text):
            name_match = _OLLAMA_NAME_RE.search(item)
            if not name_match:
                continue
            desc_match = _OLLAMA_DESC_RE.search(item)
            pulls_match = _OLLAMA_PULLS_RE.search(item)
            results.append({
                'name': name_match.group(1),
                'description': re.sub(r'\s+', ' ', desc_match.group(1)).strip() if desc_match else '',
                'pulls': pulls_match.group(1) if pulls_match else None,
                'capabilities': _OLLAMA_CAP_RE.findall(item),
                'sizes': _OLLAMA_SIZE_RE.findall(item),
            })
            if len(results) >= limit:
                break
        if not results:
            # 결과 없음은 정상일 수 있으나, 사이트 구조 변경으로 파싱이 깨졌을 가능성도 있어 로그를 남김
            logger.warning(f"Ollama search returned no results (query={query}) - site structure may have changed")
        return results

    def list_ollama_tags(self, name: str) -> list:
        """ollama.com/library/{name}/tags 파싱 — 설치 가능한 태그·크기·context window

        Returns:
            [{'tag', 'full_name', 'size_text', 'context', 'digest'}, ...]
        """
        resp = requests.get(
            f'{OLLAMA_SITE_BASE}/library/{name}/tags',
            headers=_SITE_HEADERS, timeout=15,
        )
        resp.raise_for_status()
        html = resp.text
        tags = []
        seen = set()
        # 모바일/데스크톱 레이아웃에 같은 태그가 중복 등장 — 첫 등장(정보 포함)만 사용
        for match in re.finditer(r'href="/library/' + re.escape(name) + r':([^"]+)"', html):
            tag = match.group(1)
            if tag in seen:
                continue
            seen.add(tag)
            info = _OLLAMA_TAG_INFO_RE.search(html[match.end():match.end() + 1500])
            tags.append({
                'tag': tag,
                'full_name': f'{name}:{tag}',
                'digest': info.group(1) if info else None,
                'size_text': info.group(2) if info else None,
                'context': info.group(3) if info else None,
            })
        if not tags:
            logger.warning(f"Ollama tag list empty (name={name}) - site structure may have changed")
        return tags

    # ---------- Ollama ----------

    def list_installed_models(self) -> list:
        """설치된 모델 목록 + vision capability (이름순)"""
        response = self.client.list()
        models = []
        for m in response.models:
            details = m.details
            models.append({
                'name': m.model,
                'size': m.size,
                'parameter_size': details.parameter_size if details else None,
                'quantization': details.quantization_level if details else None,
                'family': details.family if details else None,
                'modified_at': m.modified_at.isoformat() if m.modified_at else None,
                'vision': self._has_vision(m.model),
            })
        models.sort(key=lambda x: x['name'] or '')
        return models

    def _has_vision(self, name: str) -> bool:
        """Ollama show의 capabilities에 vision 포함 여부 (조회 실패 시 False)"""
        try:
            info = self.client.show(name)
            return 'vision' in (info.capabilities or [])
        except Exception:
            return False

    def delete_model(self, name: str) -> None:
        """설치된 모델 삭제"""
        self.client.delete(name)
