"""
Ollama Test Service
Structured Outputs 테스트용 — 모델 목록 조회 + format(JSON Schema) 지정 chat 실행
"""
import logging
import psycopg2
from psycopg2.extras import Json
from ollama import ChatResponse
import socket
import urllib.request
import urllib.error
import json
import subprocess
import os
import platform

from util.ollama_client import create_ollama_client
from config.db_config import get_audit_database_url

logger = logging.getLogger(__name__)

# NSSM으로 등록된 실제 서비스명. 'Ollama'로 호출하면 존재하지 않아 매번 taskkill 폴백으로 샌다.
OLLAMA_SERVICE_NAME = os.environ.get('OLLAMA_SERVICE_NAME', 'OllamaService')


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
             temperature: float = 0.0, format_spec=None, auto_unload: bool = False) -> dict:
        """
        Structured Outputs chat 실행 (stream=False)

        Args:
            model: Ollama 모델명
            prompt: 유저 프롬프트
            system: 시스템 프롬프트 (선택)
            temperature: 샘플링 온도 (구조화 출력은 0 권장)
            format_spec: None | 'json' | JSON Schema dict — Ollama format 파라미터로 전달
            auto_unload: 실행 후 자동 Unload 여부

        Returns:
            {'content': str, 'metrics': {...}}
        """
        messages = []
        if system:
            messages.append({'role': 'system', 'content': system})
        messages.append({'role': 'user', 'content': prompt})

        logger.info(f"Ollama chat (model={model}, format={'schema' if isinstance(format_spec, dict) else format_spec}, auto_unload={auto_unload})")

        # 벤치마크(auto_unload)에서만 keep_alive=0을 실어 추론 직후 즉시 언로드시킨다.
        # 요청 단위 파라미터라 vision/OCR/embedding 등 다른 서비스가 올려둔 모델의
        # 상주 정책에는 영향을 주지 않는다 — 전역 설정으로 막으면 그쪽이 서로 밀려난다.
        chat_kwargs = {}
        if auto_unload:
            chat_kwargs['keep_alive'] = 0

        try:
            response: ChatResponse = self.client.chat(
                model=model,
                messages=messages,
                format=format_spec,
                options={'temperature': temperature},
                stream=False,
                **chat_kwargs,
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
        finally:
            if auto_unload:
                logger.info(f"Triggering auto-unload for model [{model}] inside finally block")
                self.unload_vram_model(model)

    def create_benchmark_batch(self, prompt: str, system_prompt: str = None,
                               temperature: float = 0.0, format_mode: str = 'none',
                               schema_definition: str = None) -> int:
        """
        벤치마크 테스트 마스터 배치 세션을 생성하고 발급된 ID를 반환
        fail-open 수칙 준수: DB 장애 발생 시 None을 반환해 테스트 기동을 막지 않음
        """
        url = get_audit_database_url()
        if not url:
            logger.warning("Database URL not set. Benchmark history will not be saved.")
            return None
        try:
            conn = psycopg2.connect(url, connect_timeout=3)
            batch_id = None
            try:
                with conn, conn.cursor() as cur:
                    cur.execute(
                        "INSERT INTO benchmark_batch (prompt, system_prompt, temperature, format_mode, schema_definition) "
                        "VALUES (%s, %s, %s, %s, %s) RETURNING id",
                        (prompt, system_prompt, temperature, format_mode, schema_definition)
                    )
                    batch_id = cur.fetchone()[0]
            finally:
                conn.close()
            return batch_id
        except Exception as e:
            logger.warning(f"Failed to create benchmark batch in DB: {e}")
            return None

    def upsert_benchmark_result(self, batch_id: int, model_name: str, status: str,
                                response_content: str = None, metrics: dict = None,
                                schema_compliance: str = 'N/A') -> bool:
        """
        특정 배치 세션 하위의 단일 모델 테스트 지표 결과를 UPSERT 함. (중복 방지 및 재시도 덮어쓰기 보장)
        """
        if not batch_id:
            return False
        url = get_audit_database_url()
        if not url:
            return False

        m = metrics or {}
        total_duration_ms = m.get('total_duration_ms')
        load_duration_ms = m.get('load_duration_ms')
        eval_duration_ms = m.get('eval_duration_ms')
        prompt_eval_count = m.get('prompt_eval_count')
        eval_count = m.get('eval_count')
        tokens_per_second = m.get('tokens_per_second')

        try:
            conn = psycopg2.connect(url, connect_timeout=3)
            try:
                with conn, conn.cursor() as cur:
                    cur.execute(
                        "INSERT INTO benchmark_result ("
                        "   batch_id, model_name, status, response_content, "
                        "   total_duration_ms, load_duration_ms, eval_duration_ms, "
                        "   prompt_eval_count, eval_count, tokens_per_second, schema_compliance, updated_at"
                        ") VALUES ("
                        "   %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, CURRENT_TIMESTAMP"
                        ") ON CONFLICT (batch_id, model_name) DO UPDATE SET "
                        "   status = EXCLUDED.status, "
                        "   response_content = EXCLUDED.response_content, "
                        "   total_duration_ms = EXCLUDED.total_duration_ms, "
                        "   load_duration_ms = EXCLUDED.load_duration_ms, "
                        "   eval_duration_ms = EXCLUDED.eval_duration_ms, "
                        "   prompt_eval_count = EXCLUDED.prompt_eval_count, "
                        "   eval_count = EXCLUDED.eval_count, "
                        "   tokens_per_second = EXCLUDED.tokens_per_second, "
                        "   schema_compliance = EXCLUDED.schema_compliance, "
                        "   updated_at = CURRENT_TIMESTAMP",
                        (batch_id, model_name, status, response_content,
                         total_duration_ms, load_duration_ms, eval_duration_ms,
                         prompt_eval_count, eval_count, tokens_per_second, schema_compliance)
                    )
            finally:
                conn.close()
            return True
        except Exception as e:
            logger.warning(f"Failed to upsert benchmark result in DB: {e}")
            return False

    def list_benchmark_history(self, limit: int = 15) -> list:
        """
        최근 저장된 벤치마크 배치 마스터 목록 역순 조회 (최근 15개 한도)
        """
        url = get_audit_database_url()
        if not url:
            return []
        try:
            conn = psycopg2.connect(url, connect_timeout=3)
            batches = []
            try:
                with conn, conn.cursor() as cur:
                    cur.execute(
                        "SELECT id, prompt, system_prompt, temperature, format_mode, schema_definition, created_at "
                        "FROM benchmark_batch ORDER BY id DESC LIMIT %s",
                        (limit,)
                    )
                    rows = cur.fetchall()
                    for r in rows:
                        batches.append({
                            'id': r[0],
                            'prompt': r[1],
                            'system_prompt': r[2],
                            'temperature': float(r[3]) if r[3] is not None else 0.0,
                            'format_mode': r[4],
                            'schema_definition': r[5],
                            'created_at': r[6].isoformat() if r[6] else None
                        })
            finally:
                conn.close()
            return batches
        except Exception as e:
            logger.warning(f"Failed to list benchmark history from DB: {e}")
            return []

    def get_benchmark_batch_details(self, batch_id: int) -> list:
        """
        특정 배치 ID에 귀속된 상세 모델 결과 목록을 조회 (Lazy Loading 연계)
        """
        url = get_audit_database_url()
        if not url:
            return []
        try:
            conn = psycopg2.connect(url, connect_timeout=3)
            results = []
            try:
                with conn, conn.cursor() as cur:
                    cur.execute(
                        "SELECT model_name, status, response_content, total_duration_ms, load_duration_ms, "
                        "       eval_duration_ms, prompt_eval_count, eval_count, tokens_per_second, schema_compliance, updated_at "
                        "FROM benchmark_result WHERE batch_id = %s ORDER BY id ASC",
                        (batch_id,)
                    )
                    rows = cur.fetchall()
                    for r in rows:
                        results.append({
                            'model_name': r[0],
                            'status': r[1],
                            'response_content': r[2],
                            'metrics': {
                                'total_duration_ms': float(r[3]) if r[3] is not None else None,
                                'load_duration_ms': float(r[4]) if r[4] is not None else None,
                                'eval_duration_ms': float(r[5]) if r[5] is not None else None,
                                'prompt_eval_count': r[6],
                                'eval_count': r[7],
                                'tokens_per_second': float(r[8]) if r[8] is not None else None,
                            },
                            'schema_compliance': r[9],
                            'updated_at': r[10].isoformat() if r[10] else None
                        })
            finally:
                conn.close()
            return results
        except Exception as e:
            logger.warning(f"Failed to load details for batch {batch_id}: {e}")
            return []

    def is_ollama_running(self) -> bool:
        """포트 11434 연결성 조회를 통해 로컬 Ollama 데몬의 구동 상태 체크"""
        try:
            with socket.create_connection(("127.0.0.1", 11434), timeout=1.5):
                return True
        except Exception:
            return False

    def get_gpu_vram_usage(self) -> dict:
        """nvidia-smi 실측 VRAM 사용량 조회.

        /api/ps는 Ollama가 인식하는 모델만 보고하므로, 고아 llama-server 런너나
        데스크톱 앱(브라우저 등)이 점유한 VRAM은 드러나지 않는다. 실측값을 함께
        노출해야 '모델은 1개인데 VRAM은 가득 찬' 유령 점유를 진단할 수 있다.
        """
        try:
            res = subprocess.run(
                ["nvidia-smi", "--query-gpu=memory.used,memory.total",
                 "--format=csv,noheader,nounits"],
                capture_output=True, text=True, timeout=5,
            )
            if res.returncode != 0 or not res.stdout.strip():
                return {'available': False}

            used_mb, total_mb = [int(v.strip()) for v in res.stdout.strip().splitlines()[0].split(',')]
            return {
                'available': True,
                'used_mb': used_mb,
                'total_mb': total_mb,
                'usage_percent': round(used_mb / total_mb * 100, 1) if total_mb else None,
            }
        except Exception as e:
            # GPU 미탑재/드라이버 부재 환경에서도 상태 조회 전체가 막히면 안 된다 (fail-open)
            logger.warning(f"Failed to read GPU VRAM usage via nvidia-smi: {e}")
            return {'available': False}

    def get_orphan_runner_count(self) -> int:
        """Ollama가 인식하지 못하는 고아 llama-server.exe 런너 수를 반환 (윈도우 전용).

        정상 상태에서는 로드된 모델 수와 런너 수가 일치한다. 런너가 더 많으면
        이전 종료에서 정리되지 않은 고아가 VRAM을 점유하고 있다는 신호다.
        """
        if platform.system() != 'Windows':
            return 0
        try:
            res = subprocess.run(
                ["tasklist", "/FI", "IMAGENAME eq llama-server.exe", "/NH"],
                capture_output=True, text=True, timeout=5,
            )
            runners = sum(1 for line in res.stdout.splitlines() if 'llama-server.exe' in line)
            loaded = len(self.get_vram_loaded_models())
            return max(0, runners - loaded)
        except Exception as e:
            logger.warning(f"Failed to count orphan llama-server runners: {e}")
            return 0

    def get_vram_loaded_models(self) -> list:
        """Ollama 로컬 API (GET /api/ps)를 조회하여 현재 VRAM에 로드되어 있는 모델 목록 반환"""
        if not self.is_ollama_running():
            return []
        try:
            req = urllib.request.Request("http://127.0.0.1:11434/api/ps", method="GET")
            with urllib.request.urlopen(req, timeout=1.5) as resp:
                data = json.loads(resp.read().decode('utf-8'))
                models = data.get('models', [])
                result = []
                for m in models:
                    result.append({
                        'model': m.get('name') or m.get('model'),
                        'size': m.get('size'),
                        'expires_at': m.get('expires_at')
                    })
                return result
        except urllib.error.HTTPError as e:
            if e.code == 404:
                # 구버전 Ollama 등으로 인해 /api/ps 가 제공되지 않는 경우 에러 스킵
                return []
            logger.warning(f"Ollama ps API returned error {e.code}")
            return []
        except Exception as e:
            logger.warning(f"Failed to fetch loaded models from Ollama (api/ps): {e}")
            return []

    def unload_vram_model(self, model_name: str = None) -> bool:
        """
        VRAM 점유 모델을 강제 해제(keep_alive: 0)시킴. 
        model_name 미지정 시 현재 로드된 모든 모델들을 일괄 Unload 처리.
        """
        if not self.is_ollama_running():
            return False
        
        models_to_unload = []
        if model_name:
            models_to_unload.append(model_name)
        else:
            loaded = self.get_vram_loaded_models()
            models_to_unload = [m['model'] for m in loaded]

        if not models_to_unload:
            return True

        success = True
        for m in models_to_unload:
            try:
                # 공식 규격인 POST /api/generate 에 비어있는 prompt와 keep_alive: 0 전송
                payload = json.dumps({
                    "model": m,
                    "prompt": "",
                    "keep_alive": 0
                }).encode('utf-8')
                
                req = urllib.request.Request(
                    "http://127.0.0.1:11434/api/generate",
                    data=payload,
                    headers={'Content-Type': 'application/json'},
                    method="POST"
                )
                # VRAM 포화로 스와핑이 걸리면 언로드 응답도 수 초~수십 초 지연된다.
                # 3초로 끊으면 정리가 가장 필요한 순간에 언로드가 실패해 OOM에서 회복하지 못한다.
                with urllib.request.urlopen(req, timeout=30.0) as resp:
                    resp.read() # 응답 완전 소모
            except Exception as e:
                logger.warning(f"Failed to unload model {m} via api/generate (keep_alive: 0): {e}")
                success = False
        return success

    def start_ollama_daemon(self) -> bool:
        """Ollama 데몬/앱 백그라운드 기동 (윈도우 환경 전용)"""
        if self.is_ollama_running():
            return True
        try:
            # 윈도우즈 서비스 시작 시도
            res = subprocess.run(["powershell", "-Command", f"Start-Service -Name {OLLAMA_SERVICE_NAME}"], capture_output=True, text=True, timeout=5)
            if res.returncode == 0:
                logger.info("Ollama service started via PowerShell.")
                return True
        except Exception:
            pass

        # 일반 백그라운드 실행으로 폴백 (서비스 권한 거부 우회)
        try:
            logger.info("Falling back to background ollama serve daemon start...")
            # CREATE_NO_WINDOW 플래그를 주어 콘솔 팝업창을 완전히 가린 채 백그라운드 구동 보증
            subprocess.Popen(["ollama", "serve"], creationflags=0x08000000)
            return True
        except Exception as e:
            logger.error(f"Failed to start Ollama background process: {e}")
            return False

    def stop_ollama_daemon(self) -> bool:
        """Ollama 데몬 강제 종료 (Windows Taskkill 활용으로 좀비까지 완벽 제거)"""
        try:
            # 윈도우즈 서비스 정지 시도
            res = subprocess.run(["powershell", "-Command", f"Stop-Service -Name {OLLAMA_SERVICE_NAME}"], capture_output=True, text=True, timeout=5)
            if res.returncode == 0:
                logger.info("Ollama service stopped via PowerShell.")
                return True
        except Exception:
            pass

        try:
            # 일반 테스크킬 폴백
            subprocess.run(["taskkill", "/F", "/IM", "ollama.exe"], capture_output=True, timeout=3)
            # ollama.exe만 죽이면 추론 런너(llama-server.exe)가 고아로 남아 VRAM을 계속 점유한다.
            # /api/ps에는 안 잡히는 유령 점유가 되므로 런너까지 반드시 함께 정리한다.
            subprocess.run(["taskkill", "/F", "/IM", "llama-server.exe"], capture_output=True, timeout=5)
            logger.info("Ollama process and llama-server runners killed via taskkill.")
            return True
        except Exception as e:
            logger.error(f"Failed to stop Ollama process: {e}")
            return False

    def restart_ollama_daemon(self) -> bool:
        """Ollama 서비스 데몬 완전 리부트 기동"""
        self.stop_ollama_daemon()
        # 프로세스 언로드 및 소멸 안전 지연
        import time
        time.sleep(1.5)
        return self.start_ollama_daemon()

    def get_ollama_log_path(self) -> str:
        """윈도우 사용자 디렉토리를 전수 와일드카드 스캔하여 server.log 물리 주소를 NSSM(SYSTEM 권한) 환경에서도 완벽 추적"""
        # 1. 시스템 프로파일 경로 우선 스캔
        system_path = "C:\\Windows\\System32\\config\\systemprofile\\.ollama\\logs\\server.log"
        if os.path.exists(system_path):
            return system_path

        # 2. C:\Users\ 하위의 모든 사용자 폴더 전수 조사 (NSSM SYSTEM 우회 책무)
        users_root = "C:\\Users"
        if os.path.exists(users_root):
            try:
                for entry in os.listdir(users_root):
                    user_dir = os.path.join(users_root, entry)
                    if os.path.isdir(user_dir):
                        p1 = os.path.join(user_dir, ".ollama", "logs", "server.log")
                        if os.path.exists(p1):
                            return p1
                        p2 = os.path.join(user_dir, "AppData", "Local", "Ollama", "server.log")
                        if os.path.exists(p2):
                            return p2
            except Exception:
                pass

        # 3. 환경변수 기반 기본 폴백
        user_name = os.environ.get('USERNAME') or os.getlogin() or 'USER'
        p_fallback = f"C:\\Users\\{user_name}\\.ollama\\logs\\server.log"
        if os.path.exists(p_fallback):
            return p_fallback
        return ""

    def read_ollama_logs(self, lines: int = 200) -> list:
        """Ollama server.log의 최근 N줄 스트리밍 조회 (인코딩 가드 errors='ignore' 및 utf-8 준수)"""
        path = self.get_ollama_log_path()
        if not path or not os.path.exists(path):
            return [f"Ollama server.log 파일을 찾을 수 없습니다. (스캔 대상: {self.get_ollama_log_path() or '없음'})"]
        
        lines = min(max(int(lines), 1), 500)
        try:
            # errors='ignore' 수칙을 엄수하여 cp949 인코딩 크래시를 원천 차단
            with open(path, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.readlines()
                return [line.rstrip('\r\n') for line in content[-lines:]]
        except Exception as e:
            logger.warning(f"Failed to read Ollama logs: {e}")
            return [f"Ollama 로그 읽기 실패: {str(e)}"]
