"""
Palworld API Swagger paths (swagger_router에서 merge)
"""

PALWORLD_SWAGGER_PATHS = {
    "/palworld/status": {
        "get": {
            "tags": ["Palworld"],
            "summary": "서버 상태 조회 (서비스 상태 + 접속자 + 메트릭)",
            "security": [{"ApiKeyAuth": []}],
            "responses": {"200": {"description": "상태 조회 성공"}, "500": {"description": "서버 오류"}}
        }
    },
    "/palworld/start": {
        "post": {
            "tags": ["Palworld"], "summary": "서버 시작",
            "security": [{"ApiKeyAuth": []}],
            "responses": {"200": {"description": "시작 성공"}, "500": {"description": "시작 실패"}}
        }
    },
    "/palworld/stop": {
        "post": {
            "tags": ["Palworld"], "summary": "서버 중지",
            "security": [{"ApiKeyAuth": []}],
            "responses": {"200": {"description": "중지 성공"}, "500": {"description": "중지 실패"}}
        }
    },
    "/palworld/restart": {
        "post": {
            "tags": ["Palworld"], "summary": "서버 재시작",
            "security": [{"ApiKeyAuth": []}],
            "responses": {"200": {"description": "재시작 성공"}, "500": {"description": "재시작 실패"}}
        }
    },
    "/palworld/settings": {
        "get": {
            "tags": ["Palworld"], "summary": "PalWorldSettings.ini 조회",
            "security": [{"ApiKeyAuth": []}],
            "responses": {"200": {"description": "조회 성공"}, "404": {"description": "ini 파일 없음"}}
        },
        "put": {
            "tags": ["Palworld"], "summary": "PalWorldSettings.ini 수정 (서버 정지 상태에서만)",
            "security": [{"ApiKeyAuth": []}],
            "requestBody": {
                "required": True,
                "content": {"application/json": {"schema": {
                    "type": "object",
                    "example": {"ServerName": "팰 사냥터", "ExpRate": "2.0", "bCrossplay": "True"}
                }}}
            },
            "responses": {
                "200": {"description": "수정 성공"},
                "400": {"description": "잘못된 요청"},
                "409": {"description": "서버 가동 중 - 중지 후 수정 필요"}
            }
        }
    },
    "/palworld/guide": {
        "get": {
            "tags": ["Palworld"], "summary": "게임 접속 가이드 정보 (공개 주소 + ini 실제 설정값)",
            "security": [{"ApiKeyAuth": []}],
            "responses": {"200": {"description": "조회 성공 (ini 없으면 address 외 null)"}}
        }
    },
    "/palworld/history": {
        "get": {
            "tags": ["Palworld"], "summary": "메트릭 시계열 히스토리 (FPS·접속자·프레임타임 추이)",
            "security": [{"ApiKeyAuth": []}],
            "parameters": [
                {"name": "limit", "in": "query", "required": False,
                 "schema": {"type": "integer", "default": 120, "maximum": 720},
                 "description": "최근 N개 스냅샷 (10초 간격 적재)"}
            ],
            "responses": {"200": {"description": "points 배열 반환"},
                          "400": {"description": "limit 정수 아님"}}
        }
    },
    "/palworld/logs": {
        "get": {
            "tags": ["Palworld"], "summary": "서버 로그 tail (source 선택)",
            "security": [{"ApiKeyAuth": []}],
            "parameters": [
                {"name": "source", "in": "query", "required": False,
                 "schema": {"type": "string", "enum": ["audit", "events", "game", "stdout", "stderr", "flask"], "default": "game"},
                 "description": "audit=관리 행위 감사로그(DB), events=접속/퇴장 이벤트, game=엔진 로그(stdout 캡처), stderr=NSSM 표준에러, flask=관리자 서버 로그"},
                {"name": "lines", "in": "query", "required": False,
                 "schema": {"type": "integer", "default": 200, "maximum": 500}}
            ],
            "responses": {"200": {"description": "조회 성공 (exists=false면 파일 없음, log_file 경로 확인)"},
                          "400": {"description": "잘못된 source 또는 lines"}}
        }
    },
    "/palworld/backups": {
        "get": {
            "tags": ["Palworld"], "summary": "백업 목록 조회",
            "security": [{"ApiKeyAuth": []}],
            "responses": {"200": {"description": "목록 조회 성공"}}
        },
        "post": {
            "tags": ["Palworld"], "summary": "즉시 백업 실행",
            "security": [{"ApiKeyAuth": []}],
            "responses": {"200": {"description": "백업 성공"}, "404": {"description": "SaveGames 폴더 없음"}}
        }
    }
}
