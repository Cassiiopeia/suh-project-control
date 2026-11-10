"""
Claude 로그인 Gmail 계정 관리: 입력 검증, 접속 테스트 후 암호화 저장, 응답 형태(비밀번호 제외)
앱 비밀번호 평문은 메모리에서만 다루고 로그·응답·감사에 남기지 않음
"""
import re
from dataclasses import dataclass

from config import claude_login_config as config
from service import claude_login_account_repository as repository
from service import claude_login_secret_cipher as cipher
from service.claude_login_mail_client import MailClientError, verify_login

GMAIL_ADDRESS_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
GMAIL_ADDRESS_MAX_LENGTH = 320
DISPLAY_NAME_MAX_LENGTH = 100
# Google 앱 비밀번호: 영문 16자리 (화면 표시 공백은 제거 후 검사)
APP_PASSWORD_PATTERN = re.compile(r"^[A-Za-z]{16}$")


class AccountValidationError(Exception):
    """입력 형식 오류 (reason: 화면 문구 키)"""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


class AccountNotFoundError(Exception):
    """계정 id 없음"""


class SecretNotConfiguredError(Exception):
    """CLAUDE_LOGIN_ACCOUNT_SECRET 미설정"""


class AccountLoginFailedError(Exception):
    """Gmail IMAP 접속 실패 (앱 비밀번호·2단계 인증 확인)"""


@dataclass
class AccountCredential:
    """코드 대기 작업용 복호화 결과 (메모리 전용)"""
    account_id: int
    gmail_address: str
    display_name: str
    app_password: str


def list_accounts() -> list:
    return [to_account_response(account) for account in repository.list_accounts()]


def create_account(display_name, gmail_address, app_password) -> dict:
    """검증 > Gmail 접속 테스트 > 암호화 > 저장 > 응답"""
    secret = _require_secret()
    display_name = _normalize_display_name(display_name)
    gmail_address = _normalize_gmail_address(gmail_address)
    app_password = _normalize_app_password(app_password)
    _verify_or_raise(gmail_address, app_password)
    account_id = repository.insert_account(
        gmail_address, display_name, cipher.encrypt_app_password(app_password, secret), cipher.ENCRYPTION_SCHEME)
    return to_account_response(repository.find_account(account_id))


def update_account(account_id: int, display_name=None, is_enabled=None, app_password=None) -> dict:
    """전달된 항목만 수정 (앱 비밀번호 변경 시 접속 테스트 후 재암호화)"""
    account = _require_account(account_id)
    fields = {}
    if display_name is not None:
        fields["display_name"] = _normalize_display_name(display_name)
    if is_enabled is not None:
        if not isinstance(is_enabled, bool):
            raise AccountValidationError("invalid_is_enabled")
        fields["is_enabled"] = is_enabled
    if app_password is not None:
        secret = _require_secret()
        app_password = _normalize_app_password(app_password)
        _verify_or_raise(account.gmail_address, app_password)
        fields.update({"encrypted_app_password": cipher.encrypt_app_password(app_password, secret),
                       "encryption_scheme": cipher.ENCRYPTION_SCHEME, "is_last_test_failed": False})
    repository.update_account(account_id, fields)
    return to_account_response(repository.find_account(account_id))


def delete_account(account_id: int) -> dict:
    account = _require_account(account_id)
    repository.delete_account(account_id)
    return to_account_response(account)


def verify_saved_account(account_id: int) -> dict:
    """저장된 앱 비밀번호로 접속 테스트 > 결과 기록 > (응답, 성공 여부)"""
    credential = load_credential(_require_account(account_id))
    try:
        verify_login(credential.gmail_address, credential.app_password)
        is_success = True
    except MailClientError:
        is_success = False
    repository.update_account(account_id, {"is_last_test_failed": not is_success})
    return {"account": to_account_response(repository.find_account(account_id)), "is_success": is_success}


def load_enabled_credentials() -> list:
    """사용 중 계정 전체 복호화 (코드 대기 시작용)"""
    return [load_credential(account) for account in repository.list_accounts(is_enabled_only=True)]


def load_credential(account) -> AccountCredential:
    secret = _require_secret()
    app_password = cipher.decrypt_app_password(account.encrypted_app_password, account.encryption_scheme, secret)
    return AccountCredential(account.id, account.gmail_address, account.display_name, app_password)


def find_account(account_id: int):
    return repository.find_account(account_id)


def to_account_response(account) -> dict:
    """계정 > API 응답 (암호문·평문 모두 제외)"""
    return {
        "id": account.id, "display_name": account.display_name, "gmail_address": account.gmail_address,
        "is_enabled": account.is_enabled, "is_last_test_failed": account.is_last_test_failed,
        "last_success_at": account.last_success_at.isoformat() if account.last_success_at else None,
        "created_at": account.created_at.isoformat() if account.created_at else None,
    }


def _require_secret() -> str:
    secret = config.get_account_secret()
    if not secret:
        raise SecretNotConfiguredError()
    return secret


def _require_account(account_id: int):
    account = repository.find_account(account_id)
    if account is None:
        raise AccountNotFoundError(account_id)
    return account


def _verify_or_raise(gmail_address: str, app_password: str):
    try:
        verify_login(gmail_address, app_password)
    except MailClientError as error:
        raise AccountLoginFailedError(str(error)) from error


def _normalize_display_name(display_name) -> str:
    name = (display_name or "").strip() if isinstance(display_name, str) else ""
    if not name or len(name) > DISPLAY_NAME_MAX_LENGTH:
        raise AccountValidationError("invalid_display_name")
    return name


def _normalize_gmail_address(gmail_address) -> str:
    address = (gmail_address or "").strip().lower() if isinstance(gmail_address, str) else ""
    if len(address) > GMAIL_ADDRESS_MAX_LENGTH or not GMAIL_ADDRESS_PATTERN.match(address):
        raise AccountValidationError("invalid_gmail_address")
    return address


def _normalize_app_password(app_password) -> str:
    password = re.sub(r"\s", "", app_password) if isinstance(app_password, str) else ""
    if not APP_PASSWORD_PATTERN.match(password):
        raise AccountValidationError("invalid_app_password")
    return password

