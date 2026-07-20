"""Audit API swagger paths"""

AUDIT_SWAGGER_PATHS = {
    "/audit/logs": {
        "get": {
            "tags": ["Audit"],
            "summary": "관리 행위 감사로그 조회",
            "description": "카테고리/행위/성공여부/검색어 필터와 키셋 페이징(before_id)을 지원한다",
            "security": [{"ApiKeyAuth": []}],
            "parameters": [
                {"name": "category", "in": "query", "schema": {"type": "string"},
                 "description": "PALWORLD | TTS | MODEL | SYSTEM"},
                {"name": "action", "in": "query", "schema": {"type": "string"}},
                {"name": "success", "in": "query", "schema": {"type": "boolean"}},
                {"name": "search", "in": "query", "schema": {"type": "string"},
                 "description": "IP/행위/상세 부분 일치 검색"},
                {"name": "limit", "in": "query", "schema": {"type": "integer", "default": 100}},
                {"name": "before_id", "in": "query", "schema": {"type": "integer"},
                 "description": "이 id 미만 행 조회 (다음 페이지)"},
            ],
            "responses": {"200": {"description": "감사로그 행 목록"}},
        }
    }
}
