"""관제소 저장소 연결 공통 (ControlTowerStore 기반 클래스): 스레드마다 SQLite 연결(WAL), 쓰기 트랜잭션, 닫기
짧게 사는 백그라운드 스레드는 끝날 때 close_thread_connection으로 자기 연결만 닫음 (연결 누적 방지)"""
from __future__ import annotations

import sqlite3
import threading
from contextlib import contextmanager

CONNECTION_TIMEOUT_SECONDS = 10  # 쓰기 잠금 대기
BUSY_TIMEOUT_MILLISECONDS = 10000


class ThreadLocalConnectionStore:
    def __init__(self, path: str):
        self._path = path
        self._thread_local = threading.local()
        self._opened_connections: list[sqlite3.Connection] = []  # close()에서 전부 닫기 위한 추적
        self._opened_connections_lock = threading.Lock()

    def _connection(self) -> sqlite3.Connection:
        """현재 스레드 전용 연결 (없으면 생성)"""
        connection = getattr(self._thread_local, "connection", None)
        if connection is None:
            connection = sqlite3.connect(self._path, timeout=CONNECTION_TIMEOUT_SECONDS, check_same_thread=False)
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute(f"PRAGMA busy_timeout={BUSY_TIMEOUT_MILLISECONDS}")
            self._thread_local.connection = connection
            with self._opened_connections_lock:
                self._opened_connections.append(connection)
        return connection

    def close(self) -> None:
        """모든 스레드의 연결 닫기 (이후 호출 시 연결을 새로 엶)"""
        with self._opened_connections_lock:
            for connection in self._opened_connections:
                connection.close()
            self._opened_connections.clear()
            self._thread_local = threading.local()

    def close_thread_connection(self) -> None:
        """현재 스레드 연결만 닫기 (없으면 무시, 이후 호출 시 새로 엶)"""
        connection = getattr(self._thread_local, "connection", None)
        if connection is None:
            return
        with self._opened_connections_lock:
            if connection in self._opened_connections:
                self._opened_connections.remove(connection)
        connection.close()
        self._thread_local.connection = None

    @contextmanager
    def _write_transaction(self):
        """쓰기 잠금을 먼저 잡는 트랜잭션: 조회 > 기록 사이 경합 방지 (성공 시 커밋, 예외 시 롤백)"""
        connection = self._connection()
        connection.execute("BEGIN IMMEDIATE")
        try:
            yield connection
        except BaseException:
            connection.rollback()
            raise
        connection.commit()
