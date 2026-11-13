"""관제소 받을 곳 복호화 URL 메모리 캐시: (받을 곳 id, 암호문 SHA-256, 키 SHA-256) > URL 원문 (PBKDF2 반복 방지)
암호문·비밀값이 바뀌면 키가 달라져 자연히 새로 복호화, 크기 상한 초과 시 가장 오래 안 쓴 것부터 삭제, 내용은 repr·로그에 없음"""
from __future__ import annotations

import hashlib
import threading
from collections import OrderedDict

# 캐시 최대 항목 수 (받을 곳 수 기준 여유분)
DECRYPTED_URL_CACHE_MAX_ENTRIES = 256


def _digest(value: bytes | str) -> str:
    return hashlib.sha256(value.encode("utf-8") if isinstance(value, str) else bytes(value)).hexdigest()


class DecryptedUrlCache:
    def __init__(self, max_entries: int = DECRYPTED_URL_CACHE_MAX_ENTRIES):
        self._max_entries = max_entries
        self._url_by_key: OrderedDict[tuple[int, str, str], str] = OrderedDict()
        self._lock = threading.Lock()

    def __repr__(self) -> str:
        return f"DecryptedUrlCache(entries={len(self._url_by_key)})"

    @staticmethod
    def to_cache_key(destination_id: int, url_encrypted: bytes, url_key: str) -> tuple[int, str, str]:
        """(id, 암호문, 비밀 문구) > 캐시 키 (원문·비밀 문구 자체는 키에 없음)"""
        return destination_id, _digest(url_encrypted), _digest(url_key)

    def get(self, cache_key: tuple[int, str, str]) -> str | None:
        """URL 원문 (없으면 None, 있으면 최근 사용으로 이동)"""
        with self._lock:
            url = self._url_by_key.get(cache_key)
            if url is not None:
                self._url_by_key.move_to_end(cache_key)
            return url

    def put(self, cache_key: tuple[int, str, str], url: str) -> None:
        """저장 > 상한 초과분 삭제 (가장 오래 안 쓴 것부터)"""
        with self._lock:
            self._url_by_key[cache_key] = url
            self._url_by_key.move_to_end(cache_key)
            while len(self._url_by_key) > self._max_entries:
                self._url_by_key.popitem(last=False)
