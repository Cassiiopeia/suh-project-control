"""
gbrain 팀원 API 키 설정 (#221): 암호화 비밀 문구(환경변수), 다시 보기 자동 가림·실패 잠금
"""
import os

# .env: 팀원 키 원문 암호화 비밀 문구 (DB 밖 보관, 운영은 GitHub Secret FLASK_ENV_FILE)
ENV_MEMBER_KEY_SECRET = 'GBRAIN_MEMBER_KEY_SECRET'

# 다시 보기 결과 창 자동 닫힘 (초)
REVEAL_AUTO_HIDE_SECONDS = 60
# 다시 보기 관리자 키 재확인 실패 잠금: 창 안에 이 횟수 틀리면 잠금
REVEAL_FAILURE_LIMIT = 5
REVEAL_FAILURE_WINDOW_SECONDS = 600


def get_member_key_secret():
    return os.environ.get(ENV_MEMBER_KEY_SECRET) or None


def is_member_key_secret_configured() -> bool:
    return bool(get_member_key_secret())
