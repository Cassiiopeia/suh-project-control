"""
Ollama Test Service
Structured Outputs 테스트용 — 모델 목록 조회 + format(JSON Schema) 지정 chat 실행
"""
import logging
import psycopg2
from psycopg2.extras import Json
from ollama import ChatResponse

from util.ollama_client import create_ollama_client
from config.db_config import get_audit_database_url

logger = logging.getLogger(__name__)


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
             temperature: float = 0.0, format_spec=None) -> dict:
        """
        Structured Outputs chat 실행 (stream=False)

        Args:
            model: Ollama 모델명
            prompt: 유저 프롬프트
            system: 시스템 프롬프트 (선택)
            temperature: 샘플링 온도 (구조화 출력은 0 권장)
            format_spec: None | 'json' | JSON Schema dict — Ollama format 파라미터로 전달

        Returns:
            {'content': str, 'metrics': {...}}
        """
        messages = []
        if system:
            messages.append({'role': 'system', 'content': system})
        messages.append({'role': 'user', 'content': prompt})

        logger.info(f"Ollama chat (model={model}, format={'schema' if isinstance(format_spec, dict) else format_spec})")

        response: ChatResponse = self.client.chat(
            model=model,
            messages=messages,
            format=format_spec,
            options={'temperature': temperature},
            stream=False,
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
