"""백그라운드 실행 공통: 응답을 기다리게 하지 않는 부수 작업(디스코드 동기화·알림 발송)을 데몬 스레드로 실행"""
from __future__ import annotations

import threading
from typing import Callable


def run_in_background(task: Callable[[], None], thread_name: str) -> None:
    """데몬 스레드 1개로 실행 (thread_name: 스레드 덤프 구분용, 테스트는 호출 모듈의 이름을 동기 실행으로 교체)"""
    threading.Thread(target=task, daemon=True, name=thread_name).start()
