"""test_claude_login_mail_client.py — Gmail 매직링크 메일 조회"""
import imaplib
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from email.utils import format_datetime

import pytest

from service.claude_login_mail_client import (
    MailClientError, extract_magic_link, find_new_magic_link_mail)

MAGIC_LINK = 'https://claude.ai/magic-link#abc:ZGVm'
# 실제 메일 구조: 추적 링크 여러 개 + 매직링크 원문
SAMPLE_HTML = (
    '<a href="https://url8792.mail.anthropic.com/ls/click?upn=u001.aaa">Claude</a>'
    f'<a href="{MAGIC_LINK}">로그인</a>'
    '<a href="https://url8792.mail.anthropic.com/ls/click?upn=u001.bbb">도움말</a>'
)
START_TIME = datetime(2026, 10, 26, 0, 34, 0, tzinfo=timezone.utc)


def build_raw_mail(received_at, message_id='<m1@anthropic>', html=SAMPLE_HTML):
    message = EmailMessage()
    message['From'] = 'no-reply-x@mail.anthropic.com'
    message['Subject'] = 'Claude의 보안 링크가 도착했습니다'
    message['Date'] = format_datetime(received_at)
    message['Message-ID'] = message_id
    message.set_content('plain')
    message.add_alternative(html, subtype='html')
    return message.as_bytes()


class FakeImap:
    """IMAP4_SSL 대체: 호출 기록 + 고정 메일함"""

    def __init__(self, raw_mails, is_login_failing=False):
        self.raw_mails = raw_mails
        self.is_login_failing = is_login_failing
        self.calls = []

    def __call__(self, host, timeout=None):
        self.calls.append(('connect', host, timeout))
        return self

    def login(self, address, password):
        if self.is_login_failing:
            raise imaplib.IMAP4.error('AUTHENTICATIONFAILED')
        self.calls.append(('login', address))

    def select(self, mailbox, readonly=False):
        self.calls.append(('select', mailbox, readonly))
        return 'OK', [b'1']

    def search(self, charset, *criteria):
        self.calls.append(('search',) + criteria)
        ids = ' '.join(str(index + 1) for index in range(len(self.raw_mails)))
        return 'OK', [ids.encode()]

    def fetch(self, message_id, parts):
        self.calls.append(('fetch', parts))
        return 'OK', [(b'1', self.raw_mails[int(message_id) - 1])]

    def logout(self):
        self.calls.append(('logout',))


def find_with(fake, accept_after=START_TIME, processed=None):
    return find_new_magic_link_mail('me@gmail.com', 'app-password', accept_after,
                                    processed or set(), imap_factory=fake)


def test_extract_magic_link_ignores_tracking_links():
    assert extract_magic_link(SAMPLE_HTML) == MAGIC_LINK


def test_extract_magic_link_returns_none_without_link():
    assert extract_magic_link('<a href="https://example.com">x</a>') is None


def test_selects_mail_received_shortly_before_start():
    fake = FakeImap([build_raw_mail(START_TIME + timedelta(seconds=10))])
    mail = find_with(fake)
    assert mail.magic_link == MAGIC_LINK
    assert mail.message_id == '<m1@anthropic>'
    assert mail.received_at == START_TIME + timedelta(seconds=10)


def test_ignores_mail_older_than_accept_after():
    fake = FakeImap([build_raw_mail(START_TIME - timedelta(seconds=1))])
    assert find_with(fake) is None


def test_skips_already_processed_message_id():
    fake = FakeImap([build_raw_mail(START_TIME + timedelta(seconds=5))])
    assert find_with(fake, processed={'<m1@anthropic>'}) is None


def test_returns_newest_unprocessed_mail():
    fake = FakeImap([
        build_raw_mail(START_TIME + timedelta(seconds=5), '<old@anthropic>'),
        build_raw_mail(START_TIME + timedelta(seconds=50), '<new@anthropic>'),
    ])
    assert find_with(fake).message_id == '<new@anthropic>'


def test_uses_readonly_select_and_peek():
    fake = FakeImap([build_raw_mail(START_TIME + timedelta(seconds=5))])
    find_with(fake)
    assert ('select', 'INBOX', True) in fake.calls
    assert ('fetch', '(BODY.PEEK[])') in fake.calls
    search_call = next(call for call in fake.calls if call[0] == 'search')
    assert 'mail.anthropic.com' in search_call


def test_imap_login_failure_raises_mail_client_error():
    fake = FakeImap([], is_login_failing=True)
    with pytest.raises(MailClientError):
        find_with(fake)


def test_imap_connection_has_timeout():
    fake = FakeImap([])
    find_with(fake)
    connect_call = next(call for call in fake.calls if call[0] == 'connect')
    assert connect_call[2] == 30


def test_since_date_is_one_day_before_accept_after():
    # Gmail SINCE 날짜 비교 시간대 불확실 > 하루 앞당겨 검색, 정확한 비교는 received_at
    fake = FakeImap([])
    find_with(fake, accept_after=datetime(2026, 10, 26, 0, 10, tzinfo=timezone.utc))
    search_call = next(call for call in fake.calls if call[0] == 'search')
    assert '25-Oct-2026' in search_call
