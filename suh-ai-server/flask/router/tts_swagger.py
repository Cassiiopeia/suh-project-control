"""
TTS API Swagger 경로 정의 — swagger_router가 병합해 노출
"""

TTS_SWAGGER_PATHS = {
    "/tts": {
        "post": {
            "tags": ["TTS"],
            "summary": "텍스트 음성 합성 (WAV)",
            "requestBody": {
                "required": True,
                "content": {
                    "application/json": {"schema": {
                        "type": "object",
                        "required": ["text"],
                        "properties": {
                            "text": {"type": "string", "example": "안녕하세요"},
                            "engine": {"type": "string", "example": "cosyvoice",
                                       "description": "생략 시 실행 중 엔진 사용"},
                            "voice": {"type": "string", "example": "ref_a",
                                      "description": "내장 또는 등록 보이스 id (u_*)"},
                            "speed": {"type": "number", "example": 1.0,
                                      "description": "엔진이 미지원이면 무시"},
                        },
                    }},
                    "multipart/form-data": {"schema": {
                        "type": "object",
                        "required": ["text"],
                        "properties": {
                            "text": {"type": "string"},
                            "engine": {"type": "string"},
                            "prompt_wav": {"type": "string", "format": "binary",
                                           "description": "원샷 클로닝용 레퍼런스 음성 — 등록 없이 이 목소리로 합성"},
                        },
                    }},
                },
            },
            "responses": {
                "200": {"description": "WAV 오디오",
                        "content": {"audio/wav": {"schema": {"type": "string", "format": "binary"}}}},
                "400": {"description": "text 누락 또는 speed 형식 오류"},
                "503": {"description": "실행 중 엔진 없음 또는 엔진 미응답"},
            },
        }
    },
    "/tts/engines": {
        "get": {
            "tags": ["TTS"],
            "summary": "TTS 엔진 카탈로그·상태 조회",
            "responses": {"200": {"description": "엔진 목록 (status: not_installed|installing|stopped|starting|running|error)"}},
        }
    },
    "/tts/engines/{engine_id}/{action}": {
        "post": {
            "tags": ["TTS"],
            "summary": "엔진 제어 (install / start / stop)",
            "parameters": [
                {"name": "engine_id", "in": "path", "required": True,
                 "schema": {"type": "string", "enum": ["cosyvoice", "supertonic", "kokoro"]}},
                {"name": "action", "in": "path", "required": True,
                 "schema": {"type": "string", "enum": ["install", "start", "stop"]}},
            ],
            "responses": {
                "200": {"description": "제어 성공 + 최신 엔진 상태"},
                "404": {"description": "알 수 없는 엔진/동작"},
                "409": {"description": "중복 설치 또는 미설치 상태 start"},
            },
        }
    },
    "/tts/voices": {
        "get": {
            "tags": ["TTS"],
            "summary": "보이스 목록 (내장 + 사용자 등록)",
            "responses": {"200": {"description": "보이스 목록 (id, name, engine, builtin)"}},
        },
        "post": {
            "tags": ["TTS"],
            "summary": "보이스 클로닝용 레퍼런스 음성 등록",
            "requestBody": {
                "required": True,
                "content": {"multipart/form-data": {"schema": {
                    "type": "object",
                    "required": ["name", "file"],
                    "properties": {
                        "name": {"type": "string", "example": "내 목소리"},
                        "file": {"type": "string", "format": "binary",
                                 "description": "WAV, 3~30초, 10MB 이하"},
                    },
                }}},
            },
            "responses": {
                "200": {"description": "등록된 보이스 (voice.id를 POST /tts의 voice로 사용)"},
                "400": {"description": "검증 실패 (형식/길이/크기)"},
            },
        },
    },
    "/tts/voices/{voice_id}": {
        "delete": {
            "tags": ["TTS"],
            "summary": "사용자 등록 보이스 삭제",
            "parameters": [
                {"name": "voice_id", "in": "path", "required": True,
                 "schema": {"type": "string", "example": "u_abc12345"}},
            ],
            "responses": {
                "200": {"description": "삭제 완료"},
                "403": {"description": "내장 보이스는 삭제 불가"},
                "404": {"description": "보이스 없음"},
            },
        }
    },
    "/tts/engines/{engine_id}/logs": {
        "get": {
            "tags": ["TTS"],
            "summary": "엔진 컨테이너 로그 tail",
            "parameters": [
                {"name": "engine_id", "in": "path", "required": True,
                 "schema": {"type": "string"}},
            ],
            "responses": {"200": {"description": "로그 텍스트"}},
        }
    },
}
