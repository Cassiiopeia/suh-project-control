"""
사용자 보이스 저장소 — 제로샷 클로닝용 레퍼런스 음성 CRUD
DB 비의존(fail-open 철학): 음성 파일 + JSON 메타로만 관리.
SCP 배포가 덮어쓰지 않는 data/ 경로에 저장해 배포에도 유지된다.
"""
import json
import os
import threading
import uuid
from datetime import datetime

logger_name = __name__

DEFAULT_DATA_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), '..', '..', 'data', 'tts-voices'))

MAX_BYTES = 10 * 1024 * 1024  # 업로드 상한 10MB
MIN_SEC, MAX_SEC = 3.0, 30.0  # 제로샷 클로닝 권장 레퍼런스 길이
MAX_NAME_LEN = 40


def _wav_duration(data: bytes) -> float:
    """RIFF 청크를 직접 파싱해 재생 길이(초)를 구한다.
    float32 WAV는 wave 모듈이 못 읽어서(포맷 3) 직접 파싱한다."""
    if len(data) < 44 or data[:4] != b'RIFF' or data[8:12] != b'WAVE':
        raise ValueError('WAV 형식이 아닙니다 (RIFF 헤더 없음)')
    pos, byte_rate, data_size = 12, None, None
    while pos + 8 <= len(data):
        chunk_id = data[pos:pos + 4]
        size = int.from_bytes(data[pos + 4:pos + 8], 'little')
        if chunk_id == b'fmt ':
            byte_rate = int.from_bytes(data[pos + 16:pos + 20], 'little')
        elif chunk_id == b'data':
            data_size = size
        pos += 8 + size + (size % 2)  # 청크는 2바이트 정렬
    if not byte_rate or data_size is None:
        raise ValueError('WAV 헤더를 해석할 수 없습니다')
    return data_size / byte_rate


class VoiceStore:

    def __init__(self, data_dir: str = None):
        self.data_dir = data_dir or DEFAULT_DATA_DIR
        self.meta_path = os.path.join(self.data_dir, 'voices.json')
        self._lock = threading.Lock()

    # ---------- 메타 파일 ----------

    def _load(self) -> list:
        try:
            with open(self.meta_path, encoding='utf-8') as f:
                return json.load(f)
        except (OSError, json.JSONDecodeError):
            return []

    def _save(self, entries: list):
        os.makedirs(self.data_dir, exist_ok=True)
        with open(self.meta_path, 'w', encoding='utf-8') as f:
            json.dump(entries, f, ensure_ascii=False, indent=2)

    # ---------- CRUD ----------

    def list(self) -> list:
        with self._lock:
            return self._load()

    def add(self, name: str, blob: bytes) -> dict:
        """검증 후 저장. 실패 시 ValueError(한국어 사유)"""
        name = (name or '').strip()
        if not name:
            raise ValueError('보이스 이름이 필요합니다')
        if len(name) > MAX_NAME_LEN:
            raise ValueError(f'보이스 이름은 {MAX_NAME_LEN}자 이하여야 합니다')
        if len(blob) > MAX_BYTES:
            raise ValueError('파일이 너무 큽니다 (10MB 이하)')
        duration = _wav_duration(blob)
        if not (MIN_SEC <= duration <= MAX_SEC):
            raise ValueError(f'재생 길이가 {MIN_SEC:.0f}~{MAX_SEC:.0f}초여야 합니다 (현재 {duration:.1f}초)')
        # 파일명은 uuid로 정규화 — 업로드 파일명을 신뢰하지 않는다 (경로 조작 차단)
        voice_id = 'u_' + uuid.uuid4().hex[:8]
        filename = f'{voice_id}.wav'
        with self._lock:
            os.makedirs(self.data_dir, exist_ok=True)
            with open(os.path.join(self.data_dir, filename), 'wb') as f:
                f.write(blob)
            entries = self._load()
            entry = {'id': voice_id, 'name': name, 'file': filename,
                     'created_at': datetime.now().isoformat(timespec='seconds')}
            entries.append(entry)
            self._save(entries)
        return entry

    def delete(self, voice_id: str):
        """없으면 KeyError"""
        with self._lock:
            entries = self._load()
            entry = next((e for e in entries if e['id'] == voice_id), None)
            if entry is None:
                raise KeyError(voice_id)
            entries.remove(entry)
            self._save(entries)
            try:
                os.remove(os.path.join(self.data_dir, entry['file']))
            except OSError:
                pass  # 메타에서 지웠으면 파일 잔재는 치명적이지 않다

    def path(self, voice_id: str) -> str:
        """합성 시 레퍼런스 파일 절대경로. 없으면 KeyError"""
        with self._lock:
            entry = next((e for e in self._load() if e['id'] == voice_id), None)
        if entry is None:
            raise KeyError(voice_id)
        return os.path.join(self.data_dir, entry['file'])


# 모듈 싱글턴 — 라우터/어댑터/서비스가 같은 저장소를 공유한다
voice_store = VoiceStore()
