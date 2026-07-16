"""
Model Management Service
HF 허브 검색·GGUF 파일 조회 + Ollama pull/삭제/설치 목록(vision capability 포함)
"""
import json
import logging
import re

import requests
from ollama import Client

logger = logging.getLogger(__name__)

HF_API_BASE = 'https://huggingface.co/api'

# 파일명 끝의 양자화 태그 추출: gemma-3-4b-it-Q4_K_M.gguf → Q4_K_M (IQ4_XS, F16, BF16 등 포함)
_QUANT_RE = re.compile(r'[-.]((?:i?q\d[a-z0-9_]*)|f16|f32|bf16)\.gguf$', re.IGNORECASE)


class ModelService:
    """HF 허브 검색과 Ollama 모델 관리(pull/delete/list)를 담당"""

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

    def pull_model_stream(self, name: str):
        """Ollama pull 진행률 제너레이터 — NDJSON 라인 yield

        클라이언트 연결이 끊기면 WSGI가 제너레이터를 close()하고(GeneratorExit)
        ollama 클라이언트의 HTTP 스트림도 함께 닫혀 다운로드가 중단된다.
        받다 만 레이어는 Ollama가 캐시하므로 재시도 시 이어받는다.
        """
        logger.info(f"Model pull start: {name}")
        try:
            for progress in self.client.pull(name, stream=True):
                yield json.dumps({
                    'status': progress.status,
                    'total': progress.total,
                    'completed': progress.completed,
                }) + '\n'
            logger.info(f"Model pull done: {name}")
        except Exception as e:
            logger.error(f"Model pull failed ({name}): {str(e)}")
            yield json.dumps({'error': str(e)}) + '\n'
