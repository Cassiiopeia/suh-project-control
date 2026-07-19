"""
TTS 엔진 수명주기 관리 — docker CLI subprocess 제어
(palworld_service가 NSSM을 subprocess로 제어하는 것과 같은 패턴)
정책: VRAM 8GB 보호를 위해 한 번에 1개 엔진만 실행
"""
import logging
import subprocess
import threading
import time
from collections import deque

from config.tts_config import TTS_ENGINES
from service.tts.adapters import get_adapter
from service.tts.voice_store import voice_store

logger = logging.getLogger(__name__)

DOCKER_TIMEOUT = 60
INSTALL_LOG_TAIL = 15  # 설치(pull) 로그 보관 줄 수 — 폴링 응답 크기 제한
STATE_CACHE_SEC = 3    # 상태 조회 캐시 — 다중 탭 폴링이 docker 호출을 중복 발사해
                       # 도커가 느릴 때 워커 스레드풀을 고갈시키는 것 방지 (실측 장애)


class TtsService:

    def __init__(self):
        self._install_lock = threading.Lock()
        self._installs = {}  # engine_id -> {'status': 'pulling'|'done'|'error', 'error': str|None}
        self._state_lock = threading.Lock()
        self._state_cache = None   # (계산 시각, 상태 리스트)

    # ---------- docker CLI 래퍼 ----------

    def _run_docker(self, args, timeout=DOCKER_TIMEOUT, check=True):
        result = subprocess.run(['docker'] + args, capture_output=True,
                                text=True, timeout=timeout)
        if check and result.returncode != 0:
            raise RuntimeError(result.stderr.strip() or f"docker {' '.join(args)} failed")
        return result.stdout

    def _image_exists(self, image: str) -> bool:
        try:
            self._run_docker(['image', 'inspect', image])
            return True
        except RuntimeError:
            return False

    def _container_running(self, container: str) -> bool:
        out = self._run_docker(['ps', '--filter', f'name=^{container}$',
                                '--format', '{{.Names}}'])
        return container in out.split()

    # ---------- 조회 ----------

    def get_engines_state(self) -> list:
        """카탈로그 + 엔진별 상태 (관리자 화면 폴링·외부 조회용).
        짧은 캐시로 동시 폴링의 docker 호출 중복을 막는다 — 락 안에서 계산해 single-flight"""
        with self._state_lock:
            if self._state_cache and time.monotonic() - self._state_cache[0] < STATE_CACHE_SEC:
                return self._state_cache[1]
            states = self._compute_engines_state()
            self._state_cache = (time.monotonic(), states)
            return states

    def _compute_engines_state(self) -> list:
        states = []
        for engine_id, spec in TTS_ENGINES.items():
            install = self._installs.get(engine_id, {})
            try:
                if install.get('status') == 'pulling':
                    status = 'installing'
                elif self._container_running(spec['container']):
                    # 컨테이너는 떠 있어도 첫 기동은 모델 다운로드/로딩 중일 수 있다
                    status = 'running' if get_adapter(engine_id).health() else 'starting'
                elif self._image_exists(spec['image']):
                    status = 'stopped'
                else:
                    status = 'not_installed'
            except Exception as e:  # docker 데몬 다운 등 — 원인 그대로 노출 (palworld 패턴)
                logger.error(f"TTS state check failed ({engine_id}): {str(e)}")
                status = 'error'
            voices = [{'id': v['id'], 'name': v['name']} for v in spec['voices']]
            if engine_id == 'cosyvoice':
                # 사용자 등록 보이스(제로샷 클로닝)는 CosyVoice에서만 사용 가능
                voices += [{'id': v['id'], 'name': f"{v['name']} (등록됨)"}
                           for v in voice_store.list()]
            states.append({
                'id': engine_id,
                'name': spec['name'],
                'description': spec['description'],
                'languages': spec['languages'],
                'vram': spec['vram'],
                'voices': voices,
                'status': status,
                'gpu': spec.get('gpu', True),
                'install_error': install.get('error'),
                'install_progress': install.get('progress'),
            })
        return states

    def get_running_engine(self):
        """실행 중 엔진 id (없으면 None) — /tts에서 engine 생략 시 사용"""
        for engine_id, spec in TTS_ENGINES.items():
            try:
                if self._container_running(spec['container']):
                    return engine_id
            except Exception:
                continue
        return None

    # ---------- 제어 ----------

    def install(self, engine_id: str):
        """이미지 pull을 백그라운드 스레드로 시작 (download_queue_service 패턴)"""
        spec = TTS_ENGINES[engine_id]
        with self._install_lock:
            if self._installs.get(engine_id, {}).get('status') == 'pulling':
                raise ValueError('이미 설치 진행 중입니다')
            self._installs[engine_id] = {'status': 'pulling', 'error': None}
        threading.Thread(target=self._pull, args=(engine_id, spec['image']),
                         daemon=True, name=f'tts-pull-{engine_id}').start()
        self._invalidate_state_cache()

    def _invalidate_state_cache(self):
        """제어 직후 폴링이 낡은 상태를 보지 않게 캐시 폐기"""
        with self._state_lock:
            self._state_cache = None

    def _pull(self, engine_id: str, image: str):
        """pull 출력을 한 줄씩 읽어 진행 상황(progress)·로그 tail을 상태에 반영한다"""
        tail = deque(maxlen=INSTALL_LOG_TAIL)
        try:
            proc = subprocess.Popen(['docker', 'pull', image],
                                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                    text=True)
            done_layers = 0
            for raw in proc.stdout:
                line = raw.strip()
                if not line:
                    continue
                tail.append(line)
                if line.endswith('Pull complete'):
                    done_layers += 1
                with self._install_lock:
                    cur = self._installs.get(engine_id)
                    if cur is not None and cur['status'] == 'pulling':
                        cur['progress'] = f'레이어 {done_layers}개 완료 · {line}'
                        cur['log'] = list(tail)
            if proc.wait() != 0:
                raise RuntimeError(tail[-1] if tail else 'docker pull failed')
            state = {'status': 'done', 'error': None, 'progress': None}
            logger.info(f"TTS image pull done: {image}")
        except Exception as e:
            state = {'status': 'error', 'error': str(e), 'progress': None}
            logger.error(f"TTS image pull failed ({engine_id}): {str(e)}")
        state['log'] = list(tail)
        with self._install_lock:
            self._installs[engine_id] = state

    def start(self, engine_id: str):
        spec = TTS_ENGINES[engine_id]
        if not self._image_exists(spec['image']):
            raise ValueError('이미지가 설치되지 않았습니다 — 먼저 설치를 실행하세요')
        # VRAM 보호 정책: GPU 엔진은 한 번에 1개만 — GPU 엔진 시작 시 다른 GPU 엔진만 내린다.
        # CPU 엔진(supertonic 등)은 GPU를 안 쓰므로 상시 동시 가동 가능
        if spec.get('gpu', True):
            for other_id, other in TTS_ENGINES.items():
                if (other_id != engine_id and other.get('gpu', True)
                        and self._container_running(other['container'])):
                    self._run_docker(['stop', other['container']], timeout=120)
                    logger.info(f"TTS engine stopped for switch: {other_id}")
        # 이전 컨테이너 잔재 제거 (없으면 무시) 후 새로 기동
        self._run_docker(['rm', '-f', spec['container']], check=False)
        args = (['run', '-d', '--name', spec['container'],
                 '--restart', 'unless-stopped',
                 '-p', f"{spec['port']}:{spec['port']}"]
                + spec['docker_args'] + [spec['image']] + spec['command'])
        self._run_docker(args, timeout=300)
        self._invalidate_state_cache()
        logger.info(f"TTS engine started: {engine_id}")

    def stop(self, engine_id: str):
        self._run_docker(['stop', TTS_ENGINES[engine_id]['container']], timeout=120)
        self._invalidate_state_cache()
        logger.info(f"TTS engine stopped: {engine_id}")

    def logs(self, engine_id: str) -> str:
        """로그 tail — 설치 중엔 pull 로그, 그 외엔 컨테이너 로그 (stderr 포함)"""
        install = self._installs.get(engine_id, {})
        if install.get('status') == 'pulling':
            lines = install.get('log') or ['(아직 출력 없음)']
            return '[이미지 다운로드 중]\n' + '\n'.join(lines)
        result = subprocess.run(
            ['docker', 'logs', '--tail', '80', TTS_ENGINES[engine_id]['container']],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, timeout=DOCKER_TIMEOUT)
        if result.returncode != 0:
            out = result.stdout.strip()
            if 'No such container' in out:
                raise RuntimeError('컨테이너가 아직 없습니다 — 엔진을 시작하면 로그가 생성됩니다')
            raise RuntimeError(out or 'docker logs failed')
        return result.stdout
