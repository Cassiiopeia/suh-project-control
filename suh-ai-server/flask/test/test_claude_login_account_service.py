"""test_claude_login_account_service.py — 계정 검증·접속 테스트 후 저장·응답에 비밀번호 없음"""
from datetime import datetime, timezone
from unittest.mock import patch

import pytest

from service import claude_login_account_service as account_service
from service import claude_login_secret_cipher as cipher
from service.claude_login_account_repository import ClaudeLoginAccount
from service.claude_login_mail_client import MailClientError

NOW = datetime(2026, 11, 10, 5, 0, tzinfo=timezone.utc)
APP_PASSWORD = 'abcdefghijklmnop'


@pytest.fixture(autouse=True)
def configured(monkeypatch):
    monkeypatch.setenv('CLAUDE_LOGIN_ACCOUNT_SECRET', 'test-secret')
    monkeypatch.setattr(cipher, 'PBKDF2_ITERATIONS', 1000)


class FakeRepository:
    """claude_login_account_repository 대체: 메모리 저장"""

    def __init__(self):
        self.accounts = {}

    def insert_account(self, gmail_address, display_name, encrypted_app_password, encryption_scheme):
        account_id = len(self.accounts) + 1
        self.accounts[account_id] = ClaudeLoginAccount(
            account_id, gmail_address, display_name, encrypted_app_password, encryption_scheme,
            True, None, False, NOW, NOW)
        return account_id

    def find_account(self, account_id):
        return self.accounts.get(account_id)

    def list_accounts(self, is_enabled_only=False):
        return [account for account in self.accounts.values() if account.is_enabled or not is_enabled_only]

    def update_account(self, account_id, fields):
        account = self.accounts.get(account_id)
        for name, value in fields.items():
            setattr(account, name, value)
        return account is not None

    def delete_account(self, account_id):
        return self.accounts.pop(account_id, None) is not None


@pytest.fixture
def repository():
    fake = FakeRepository()
    with patch.object(account_service, 'repository', fake):
        yield fake


def create(repository, verify=None, **overrides):
    values = {'display_name': '회사', 'gmail_address': 'Work@Gmail.com ', 'app_password': 'abcd efgh ijkl mnop'}
    values.update(overrides)
    with patch.object(account_service, 'verify_login', verify or (lambda *a: None)):
        return account_service.create_account(**values)


def test_create_normalizes_and_encrypts(repository):
    response = create(repository)
    stored = repository.accounts[response['id']]
    assert stored.gmail_address == 'work@gmail.com'
    assert APP_PASSWORD.encode() not in bytes(stored.encrypted_app_password)
    assert account_service.load_credential(stored).app_password == APP_PASSWORD


def test_response_never_contains_password(repository):
    response = create(repository)
    assert 'app_password' not in response
    assert 'encrypted_app_password' not in response
    assert APP_PASSWORD not in repr(response)


def test_create_tests_login_with_normalized_values(repository):
    calls = []
    create(repository, verify=lambda address, password: calls.append((address, password)))
    assert calls == [('work@gmail.com', APP_PASSWORD)]


def test_create_login_failure_saves_nothing(repository):
    def failing(*args):
        raise MailClientError('imap login failed: error')
    with pytest.raises(account_service.AccountLoginFailedError):
        create(repository, verify=failing)
    assert repository.accounts == {}


@pytest.mark.parametrize('field, value, reason', [
    ('display_name', '  ', 'invalid_display_name'),
    ('gmail_address', 'not-an-address', 'invalid_gmail_address'),
    ('app_password', 'short', 'invalid_app_password'),
    ('app_password', None, 'invalid_app_password'),
])
def test_create_validation_errors(repository, field, value, reason):
    with pytest.raises(account_service.AccountValidationError) as error:
        create(repository, **{field: value})
    assert error.value.reason == reason


def test_create_without_secret_raises(repository, monkeypatch):
    monkeypatch.delenv('CLAUDE_LOGIN_ACCOUNT_SECRET')
    with pytest.raises(account_service.SecretNotConfiguredError):
        create(repository)


def test_update_password_retests_and_reencrypts(repository):
    account_id = create(repository)['id']
    repository.accounts[account_id].is_last_test_failed = True
    calls = []
    with patch.object(account_service, 'verify_login', lambda address, password: calls.append(password)):
        account_service.update_account(account_id, app_password='zyxwvutsrqponmlk')
    stored = repository.accounts[account_id]
    assert calls == ['zyxwvutsrqponmlk']
    assert account_service.load_credential(stored).app_password == 'zyxwvutsrqponmlk'
    assert stored.is_last_test_failed is False


def test_update_toggle_only_skips_login_test(repository):
    account_id = create(repository)['id']
    with patch.object(account_service, 'verify_login', side_effect=AssertionError('no login')):
        response = account_service.update_account(account_id, is_enabled=False)
    assert response['is_enabled'] is False


def test_update_rejects_non_bool_is_enabled(repository):
    account_id = create(repository)['id']
    with pytest.raises(account_service.AccountValidationError):
        account_service.update_account(account_id, is_enabled='yes')


def test_missing_account_raises_not_found(repository):
    with pytest.raises(account_service.AccountNotFoundError):
        account_service.delete_account(99)


def test_verify_saved_account_records_failure(repository):
    account_id = create(repository)['id']

    def failing(*args):
        raise MailClientError('imap login failed: error')
    with patch.object(account_service, 'verify_login', failing):
        result = account_service.verify_saved_account(account_id)
    assert result['is_success'] is False
    assert repository.accounts[account_id].is_last_test_failed is True
