"""
팀 브레인 서버 작업 (Flask = LocalSystem): 관리자 토큰, gbrain 설정·스키마, NSSM 서비스, nginx 경로
모든 단계는 다시 실행해도 같은 결과 (있으면 유지), 비밀값(DB 비번·토큰)은 로그·응답에 넣지 않음
"""
import glob
import json
import logging
import os
import re
import secrets
import subprocess
from urllib.parse import quote, urlsplit

from config import gbrain_server_config as config
from service.gbrain_server_service import GbrainServerError

logger = logging.getLogger(__name__)

# 관리자 토큰 바이트 수 (base64url 64자, gbrain 규칙 32자 이상 [A-Za-z0-9_-])
ADMIN_TOKEN_BYTES = 48
# 개인 브레인 설정에서 팀 브레인으로 옮기는 값 (임베딩은 같은 Ollama 모델이어야 검색 가능)
SHARED_CONFIG_KEYS = ('embedding_model', 'embedding_dimensions', 'schema_pack')
# 명령 출력 중 오류 사유로 남길 최대 길이
COMMAND_OUTPUT_MAX_LENGTH = 300


class GbrainTeamProvisioner:
    # ---------- 관리자 토큰 ----------
    def ensure_admin_token(self, instance) -> bool:
        """없을 때만 생성 > SYSTEM·Administrators 만 읽기, 반환: 새로 만들었으면 True"""
        token_path = instance.admin_token_file
        if os.path.exists(token_path):
            return False
        os.makedirs(os.path.dirname(token_path), exist_ok=True)
        # BOM 없는 한 줄 (실행기의 set /p 가 첫 줄을 그대로 읽음)
        with open(token_path, 'w', encoding='ascii', newline='') as token_stream:
            token_stream.write(secrets.token_urlsafe(ADMIN_TOKEN_BYTES))
        self._restrict_to_system(token_path)
        logger.info(f'[gbrain team] admin token created : brain={instance.brain_id}')
        return True

    def has_admin_token(self, instance) -> bool:
        return os.path.exists(instance.admin_token_file)

    # ---------- gbrain 설정·스키마 ----------
    def has_brain_config(self, instance) -> bool:
        return os.path.exists(config.get_gbrain_config_path(instance.gbrain_home))

    def build_database_url(self, instance, writer_password: str) -> str:
        """서버 내부 접속: postgresql://<쓰기 계정>:<비번>@<개인 브레인과 같은 호스트:포트>/<DB>"""
        database_host, database_port = self._read_personal_database_address()
        return (f'postgresql://{instance.writer_role}:{quote(writer_password, safe="")}@'
                f'{database_host}:{database_port}/{instance.database_name}')

    def write_brain_config(self, instance, database_url: str) -> None:
        """기존 스키마가 있는 브레인(예: passQL): 설정 파일 쓰기 > 대기 중 마이그레이션만 적용"""
        personal_config = self._read_personal_config()
        brain_config = {'engine': 'postgres', 'database_url': database_url,
                        **{key: personal_config[key] for key in SHARED_CONFIG_KEYS if key in personal_config}}
        config_path = config.get_gbrain_config_path(instance.gbrain_home)
        os.makedirs(os.path.dirname(config_path), exist_ok=True)
        with open(config_path, 'w', encoding='utf-8') as config_stream:
            json.dump(brain_config, config_stream, indent=2)
        self._restrict_to_system(config_path)
        self._run_gbrain(instance, ['init', '--migrate-only'], 'migrate')

    def initialize_new_brain(self, instance, database_url: str) -> None:
        """빈 DB: gbrain init 이 스키마·설정 파일을 함께 만듦 (임베딩은 개인 브레인과 같은 모델)"""
        personal_config = self._read_personal_config()
        arguments = ['init', '--url', database_url, '--non-interactive', '--skip-embed-check', '--db-only']
        if personal_config.get('embedding_model'):
            arguments += ['--embedding-model', str(personal_config['embedding_model'])]
        if personal_config.get('embedding_dimensions'):
            arguments += ['--embedding-dimensions', str(personal_config['embedding_dimensions'])]
        self._run_gbrain(instance, arguments, 'init')
        self._restrict_to_system(config.get_gbrain_config_path(instance.gbrain_home))

    # ---------- NSSM 서비스 ----------
    def install_service(self, instance) -> None:
        """setup-gbrain-http.ps1 -SkipInstall (개인 브레인과 같은 bun·gbrain, 서비스·포트·폴더만 다름) > /health 확인"""
        command = [
            'powershell', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', os.path.abspath(config.GBRAIN_SETUP_SCRIPT_PATH),
            '-SkipInstall', '-ServiceName', instance.service_name, '-Port', str(instance.port),
            '-GbrainHome', instance.gbrain_home, '-BunHome', config.GBRAIN_BUN_HOME,
            '-AdminTokenPath', instance.admin_token_file, '-LogPath', instance.log_path,
            '-DisplayName', f'gbrain team brain {instance.brain_id}',
        ]
        self._run_command(command, config.GBRAIN_TEAM_SETUP_TIMEOUT_SECONDS, 'service_install_failed',
                          f'[gbrain team] service install brain={instance.brain_id}')

    # ---------- nginx 공개 경로 ----------
    def get_nginx_map_path(self, instance) -> str:
        return os.path.join(config.GBRAIN_TEAM_ROOT, 'nginx', f'{instance.brain_id}.map')

    def is_nginx_route_published(self, instance) -> bool:
        """map 파일이 지금 포트와 같은 내용인지 (dry_run 용, 읽기만)"""
        return self._read_text(self.get_nginx_map_path(instance)) == self._build_nginx_map_line(instance)

    def publish_nginx_route(self, instance) -> bool:
        """map 파일(<project> 127.0.0.1:<port>;) > nginx -t > reload, 검사 실패면 이전 내용 복원, 반환: 바뀌었으면 True"""
        map_path = self.get_nginx_map_path(instance)
        map_line = self._build_nginx_map_line(instance)
        previous_line = self._read_text(map_path)
        if previous_line == map_line:
            return False
        os.makedirs(os.path.dirname(map_path), exist_ok=True)
        with open(map_path, 'w', encoding='ascii', newline='\n') as map_stream:
            map_stream.write(map_line)
        try:
            self._reload_nginx()
        except GbrainServerError:
            # 복원 (새 파일이었으면 삭제) > 기존 nginx 설정 유지
            if previous_line is None:
                os.remove(map_path)
            else:
                with open(map_path, 'w', encoding='ascii', newline='\n') as map_stream:
                    map_stream.write(previous_line)
            raise
        return True

    @staticmethod
    def _build_nginx_map_line(instance) -> str:
        return f'{instance.brain_id} 127.0.0.1:{instance.port};\n'

    def _reload_nginx(self) -> None:
        nginx_directory = self._find_nginx_directory()
        nginx_executable = os.path.join(nginx_directory, 'nginx.exe')
        self._run_command([nginx_executable, '-t'], 30, 'nginx_test_failed', '[gbrain team] nginx -t',
                          working_directory=nginx_directory)
        self._run_command([nginx_executable, '-s', 'reload'], 30, 'nginx_reload_failed', '[gbrain team] nginx reload',
                          working_directory=nginx_directory)

    @staticmethod
    def _find_nginx_directory() -> str:
        candidates = sorted(path for path in glob.glob(config.GBRAIN_NGINX_GLOB)
                            if os.path.exists(os.path.join(path, 'nginx.exe')))
        if not candidates:
            raise GbrainServerError('nginx 설치 폴더를 찾지 못했어요', 'nginx_not_found', 500)
        return candidates[-1]

    # ---------- 내부 ----------
    def _run_gbrain(self, instance, arguments: list, step_name: str) -> None:
        """팀 폴더를 GBRAIN_HOME·HOME 으로 고정 > 개인 브레인(~/.gbrain) 설정을 건드리지 않음"""
        bun_directory = os.path.join(config.GBRAIN_BUN_HOME, '.bun')
        environment = {
            **os.environ, 'GBRAIN_HOME': instance.gbrain_home, 'HOME': instance.gbrain_home,
            'USERPROFILE': instance.gbrain_home, 'GBRAIN_INIT_SKIP_EMBED_CHECK': '1',
            'PATH': os.path.join(bun_directory, 'bin') + os.pathsep + os.environ.get('PATH', ''),
        }
        command = [os.path.join(bun_directory, 'bin', 'bun.exe'),
                   os.path.join(bun_directory, 'install', 'global', 'node_modules', 'gbrain', 'src', 'cli.ts'),
                   *arguments]
        # 로그에는 하위 명령 이름만 (init --url 에 DB 비번이 들어 있음)
        self._run_command(command, config.GBRAIN_TEAM_INIT_TIMEOUT_SECONDS, f'gbrain_{step_name}_failed',
                          f'[gbrain team] gbrain {step_name} brain={instance.brain_id}', environment=environment,
                          working_directory=instance.gbrain_home)

    @staticmethod
    def _run_command(command: list, timeout_seconds: int, error_code: str, log_label: str,
                     environment=None, working_directory=None) -> None:
        """실패 사유는 출력 끝부분만 (DB 비번이 섞일 수 있는 명령줄은 남기지 않음)"""
        if working_directory:
            os.makedirs(working_directory, exist_ok=True)
        try:
            result = subprocess.run(command, capture_output=True, text=True, timeout=timeout_seconds,
                                    env=environment, cwd=working_directory, encoding='utf-8', errors='replace')
        except (OSError, subprocess.SubprocessError) as error:
            logger.error(f'{log_label} failed : {type(error).__name__}')
            raise GbrainServerError(f'서버 명령을 실행하지 못했어요 ({type(error).__name__})', error_code, 500)
        if result.returncode != 0:
            output_tail = GbrainTeamProvisioner._mask_database_password((result.stderr or result.stdout or '').strip())
            output_tail = output_tail[-COMMAND_OUTPUT_MAX_LENGTH:]
            logger.error(f'{log_label} failed : exit {result.returncode} {output_tail}')
            raise GbrainServerError(f'서버 명령이 실패했어요 (exit {result.returncode}): {output_tail}', error_code, 500)
        logger.info(f'{log_label} ok')

    @staticmethod
    def _mask_database_password(text: str) -> str:
        """postgresql://계정:비번@ > postgresql://계정:***@"""
        return re.sub(r'(postgres(?:ql)?://[^:/@\s]+:)[^@\s]+@', r'\1***@', text)

    @staticmethod
    def _read_personal_config() -> dict:
        try:
            with open(config.get_gbrain_config_path(), encoding='utf-8') as config_stream:
                personal_config = json.load(config_stream)
        except (OSError, ValueError):
            raise GbrainServerError('개인 gbrain 설정 파일을 읽지 못했어요 (임베딩 모델 기준값)', 'personal_config_unreadable', 500)
        return personal_config if isinstance(personal_config, dict) else {}

    def read_personal_database_url(self) -> str:
        """개인 브레인 DB 접속 문자열 (슈퍼유저, 이미 있는 팀 DB 손보기에만 씀, 값은 로그·응답에 넣지 않음)"""
        database_url = str(self._read_personal_config().get('database_url', ''))
        if not database_url:
            raise GbrainServerError('개인 gbrain 설정에서 DB 주소를 찾지 못했어요', 'personal_config_unreadable', 500)
        return database_url

    def _read_personal_database_address(self) -> tuple:
        database_url = str(self._read_personal_config().get('database_url', ''))
        parts = urlsplit(database_url)
        if not parts.hostname or not parts.port:
            raise GbrainServerError('개인 gbrain 설정에서 DB 주소를 찾지 못했어요', 'personal_config_unreadable', 500)
        return parts.hostname, parts.port

    @staticmethod
    def _read_text(path: str):
        try:
            with open(path, encoding='ascii') as text_stream:
                return text_stream.read()
        except OSError:
            return None

    @staticmethod
    def _restrict_to_system(path: str) -> None:
        """상속 끊기 > SYSTEM·Administrators 만 (Windows 외 환경·시험에서는 건너뜀)"""
        if os.name != 'nt':
            return
        subprocess.run(['icacls', path, '/inheritance:r', '/grant:r', 'SYSTEM:F', 'Administrators:F'],
                       capture_output=True, text=True, timeout=30)


gbrain_team_provisioner = GbrainTeamProvisioner()
