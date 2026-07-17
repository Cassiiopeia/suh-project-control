"""
TTS 엔진 수명주기 관리 — docker CLI subprocess 제어
(palworld_service가 NSSM을 subprocess로 제어하는 것과 같은 패턴)
정책: VRAM 8GB 보호를 위해 한 번에 1개 엔진만 실행
"""
import logging
import subprocess
import threading

from config.tts_config import TTS_ENGINES
from service.tts.adapters import get_adapter

logger = logging.getLogger(__name__)

DOCKER_TIMEOUT = 60
PULL_TIMEOUT = 3600  # 이미지가 수 GB — 서버 회선 기준 여유값


class TtsService:

    def __init__(self):
        self._install_lock = threading.Lock()
        self._installs = {}  # engine_id -> {'status': 'pulling'|'done'|'error', 'error': str|None}

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
        """카탈로그 + 엔진별 상태 (관리자 화면 폴링·외부 조회용)"""
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
            states.append({
                'id': engine_id,
                'name': spec['name'],
                'description': spec['description'],
                'languages': spec['languages'],
                'vram': spec['vram'],
                'voices': [{'id': v['id'], 'name': v['name']} for v in spec['voices']],
                'status': status,
                'install_error': install.get('error'),
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

    def _pull(self, engine_id: str, image: str):
        try:
            self._run_docker(['pull', image], timeout=PULL_TIMEOUT)
            state = {'status': 'done', 'error': None}
            logger.info(f"TTS image pull done: {image}")
        except Exception as e:
            state = {'status': 'error', 'error': str(e)}
            logger.error(f"TTS image pull failed ({engine_id}): {str(e)}")
        with self._install_lock:
            self._installs[engine_id] = state

    def start(self, engine_id: str):
        spec = TTS_ENGINES[engine_id]
        if not self._image_exists(spec['image']):
            raise ValueError('이미지가 설치되지 않았습니다 — 먼저 설치를 실행하세요')
        # 1개만 실행 정책 — 다른 실행 중 엔진을 먼저 내린다
        for other_id, other in TTS_ENGINES.items():
            if other_id != engine_id and self._container_running(other['container']):
                self._run_docker(['stop', other['container']], timeout=120)
                logger.info(f"TTS engine stopped for switch: {other_id}")
        # 이전 컨테이너 잔재 제거 (없으면 무시) 후 새로 기동
        self._run_docker(['rm', '-f', spec['container']], check=False)
        args = (['run', '-d', '--name', spec['container'],
                 '--restart', 'unless-stopped',
                 '-p', f"{spec['port']}:{spec['port']}"]
                + spec['docker_args'] + [spec['image']] + spec['command'])
        self._run_docker(args, timeout=300)
        logger.info(f"TTS engine started: {engine_id}")

    def stop(self, engine_id: str):
        self._run_docker(['stop', TTS_ENGINES[engine_id]['container']], timeout=120)
        logger.info(f"TTS engine stopped: {engine_id}")

    def logs(self, engine_id: str) -> str:
        """컨테이너 로그 tail — 설치/기동 진행 상황 표시용 (stderr 포함)"""
        result = subprocess.run(
            ['docker', 'logs', '--tail', '80', TTS_ENGINES[engine_id]['container']],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, timeout=DOCKER_TIMEOUT)
        if result.returncode != 0:
            raise RuntimeError(result.stdout.strip() or 'docker logs failed')
        return result.stdout
