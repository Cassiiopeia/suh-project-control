"""
Ollama Test Service
Structured Outputs 테스트용 — 모델 목록 조회 + format(JSON Schema) 지정 chat 실행
"""
import logging
from ollama import ChatResponse

from util.ollama_client import create_ollama_client

logger = logging.getLogger(__name__)


def _ns_to_ms(value):
    """나노초 → 밀리초 (Ollama 메트릭은 ns 단위, 없으면 None)"""
    return round(value / 1_000_000, 1) if value else None


class OllamaService:
    """Handles Ollama model listing and structured-output chat"""

    def __init__(self, ollama_url: str = "http://127.0.0.1:11434"):
        self.ollama_url = ollama_url.rstrip('/')
        self.client = create_ollama_client(self.ollama_url)

    def list_models(self) -> list:
        """
        설치된 Ollama 모델 목록 조회

        Returns:
            [{'name': 'gemma3:4b', 'size': 3338801718, 'parameter_size': '4.3B', 'family': 'gemma3'}, ...]
        """
        response = self.client.list()
        models = []
        for m in response.models:
            details = m.details
            models.append({
                'name': m.model,
                'size': m.size,
                'parameter_size': details.parameter_size if details else None,
                'family': details.family if details else None,
            })
        # 이름순 정렬 — 드롭다운에서 찾기 쉽게
        models.sort(key=lambda x: x['name'] or '')
        return models

    def chat(self, model: str, prompt: str, system: str = None,
             temperature: float = 0.0, format_spec=None) -> dict:
        """
        Structured Outputs chat 실행 (stream=False)

        Args:
            model: Ollama 모델명
            prompt: 유저 프롬프트
            system: 시스템 프롬프트 (선택)
            temperature: 샘플링 온도 (구조화 출력은 0 권장)
            format_spec: None | 'json' | JSON Schema dict — Ollama format 파라미터로 전달

        Returns:
            {'content': str, 'metrics': {...}}
        """
        messages = []
        if system:
            messages.append({'role': 'system', 'content': system})
        messages.append({'role': 'user', 'content': prompt})

        logger.info(f"Ollama chat (model={model}, format={'schema' if isinstance(format_spec, dict) else format_spec})")

        response: ChatResponse = self.client.chat(
            model=model,
            messages=messages,
            format=format_spec,
            options={'temperature': temperature},
            stream=False,
        )

        eval_duration_ms = _ns_to_ms(response.eval_duration)
        tokens_per_second = None
        if response.eval_count and eval_duration_ms:
            tokens_per_second = round(response.eval_count / (eval_duration_ms / 1000), 1)

        return {
            'content': response.message.content,
            'metrics': {
                'total_duration_ms': _ns_to_ms(response.total_duration),
                'load_duration_ms': _ns_to_ms(response.load_duration),
                'prompt_eval_count': response.prompt_eval_count,
                'eval_count': response.eval_count,
                'eval_duration_ms': eval_duration_ms,
                'tokens_per_second': tokens_per_second,
            },
        }
