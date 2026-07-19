"""Ollama Client 공용 팩토리

타임아웃 없이 Client를 만들면 Ollama가 응답하지 않을 때 waitress 워커
스레드가 무한 대기해 서버 전체가 행에 걸린다 (#109). Ollama를 쓰는
모든 서비스는 이 팩토리로 Client를 생성한다.
"""
import httpx
from ollama import Client

# connect: Ollama 다운 시 빠르게 실패시키기 위해 짧게
OLLAMA_CONNECT_TIMEOUT_SEC = 5
# read/write: 대형 모델 생성도 여유 있게. 스트리밍(pull 등)은 청크 간격 기준으로
# 판정되므로 정상 진행 중인 장시간 다운로드는 끊기지 않는다
OLLAMA_TIMEOUT_SEC = 300


def create_ollama_client(ollama_url: str = "http://127.0.0.1:11434") -> Client:
    # 명시적으로 host를 지정해 OLLAMA_HOST 환경변수(0.0.0.0)에 의존하지 않음
    return Client(
        host=ollama_url.rstrip('/'),
        timeout=httpx.Timeout(OLLAMA_TIMEOUT_SEC, connect=OLLAMA_CONNECT_TIMEOUT_SEC),
    )
