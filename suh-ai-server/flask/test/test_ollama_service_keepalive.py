"""ollama_service.chat 의 keep_alive 전달 규칙 테스트

벤치마크(auto_unload=True)만 keep_alive=0으로 즉시 언로드시키고,
그 외 서비스(vision/OCR/embedding 등) 호출은 keep_alive를 보내지 않아
Ollama 기본 상주 정책을 그대로 따르는지 검증한다.
"""
import pytest

from service.ollama_service import OllamaService


class _FakeMessage:
    content = '{"ok":true}'


class _FakeResponse:
    message = _FakeMessage()
    total_duration = 2_000_000_000
    load_duration = 40_000_000
    prompt_eval_count = 10
    eval_count = 20
    eval_duration = 1_000_000_000


class _FakeClient:
    def __init__(self):
        self.kwargs = None

    def chat(self, **kwargs):
        self.kwargs = kwargs
        return _FakeResponse()


@pytest.fixture
def service(monkeypatch):
    svc = OllamaService()
    fake = _FakeClient()
    svc.client = fake
    # 언로드는 실제 HTTP를 타지 않도록 무력화 (여기 관심사는 chat 파라미터)
    monkeypatch.setattr(svc, 'unload_vram_model', lambda model_name=None: True)
    return svc, fake


def test_benchmark_sends_keep_alive_zero(service):
    """auto_unload=True(벤치마크)면 keep_alive=0을 실어 즉시 언로드시킨다"""
    svc, fake = service
    svc.chat(model='exaone-deep:2.4b', prompt='hi', auto_unload=True)
    assert fake.kwargs['keep_alive'] == 0


def test_normal_call_omits_keep_alive(service):
    """일반 서비스 호출은 keep_alive를 보내지 않아 다른 모델 상주에 간섭하지 않는다"""
    svc, fake = service
    svc.chat(model='gemma3:4b', prompt='hi', auto_unload=False)
    assert 'keep_alive' not in fake.kwargs


def test_default_is_no_keep_alive(service):
    """auto_unload 미지정 시 기본은 전역 정책 유지(미전송)"""
    svc, fake = service
    svc.chat(model='gemma3:4b', prompt='hi')
    assert 'keep_alive' not in fake.kwargs
