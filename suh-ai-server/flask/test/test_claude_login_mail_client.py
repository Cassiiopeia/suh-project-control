"""test_claude_login_mail_client.py — Gmail 매직링크 메일 조회"""
import imaplib
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from email.utils import format_datetime

import pytest

from service.claude_login_mail_client import (
    MailClientError, extract_magic_link, find_new_magic_link_mail, verify_login)

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


def test_extract_magic_link_accepts_client_query_before_fragment():
    # 2026-10-31 메일 형식 변경: magic-link?client=... #토큰
    link = 'https://claude.ai/magic-link?client=abc123#abc:ZGVm'
    assert extract_magic_link(f'<a href="{link}">로그인</a>') == link


@pytest.mark.parametrize('link', [
    # 2026-11-13 메일 형식 변경: magic-link/{기기}#토큰 (#190)
    'https://claude.ai/magic-link/android#abc:ZGVm',
    'https://claude.ai/magic-link/ios#abc:ZGVm',
    # 경로 + 쿼리 조합 (향후 변경 대비)
    'https://claude.ai/magic-link/android?client=abc123#abc:ZGVm',
])
def test_extract_magic_link_accepts_path_after_magic_link(link):
    assert extract_magic_link(f'<a href="{link}">로그인</a>') == link


def test_extract_magic_link_accepts_single_quoted_href():
    assert extract_magic_link(f"<a href='{MAGIC_LINK}'>로그인</a>") == MAGIC_LINK


def test_extract_magic_link_decodes_html_entities():
    html = '<a href="https://claude.ai/magic-link?client=a&amp;source=b#abc:ZGVm">로그인</a>'
    assert extract_magic_link(html) == 'https://claude.ai/magic-link?client=a&source=b#abc:ZGVm'


def test_extract_magic_link_returns_none_without_link():
    assert extract_magic_link('<a href="https://example.com">x</a>') is None


def test_extract_magic_link_requires_token_fragment():
    # 토큰(#) 없는 magic-link 안내 링크는 제외
    assert extract_magic_link('<a href="https://claude.ai/magic-link/help">x</a>') is None


def test_search_covers_anthropic_and_claude_sender_domains():
    fake = FakeImap([])
    find_with(fake)
    search_call = next(call for call in fake.calls if call[0] == 'search')
    assert search_call[1:6] == ('OR', 'FROM', 'anthropic.com', 'FROM', 'claude.com')


def test_unrecognized_mail_logs_link_paths_once(caplog):
    html = '<a href="https://claude.ai/login-link/xyz#token">로그인</a>'
    fake = FakeImap([build_raw_mail(START_TIME + timedelta(seconds=5), '<changed@anthropic>', html)])
    with caplog.at_level('WARNING'):
        assert find_with(fake) is None
        assert find_with(fake) is None
    warnings = [record.getMessage() for record in caplog.records if 'not recognized' in record.getMessage()]
    assert len(warnings) == 1
    assert 'claude_paths=/login-link/xyz' in warnings[0]
    assert 'token' not in warnings[0]


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
    assert 'anthropic.com' in search_call


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


def test_verify_login_opens_inbox_readonly_and_logs_out():
    fake = FakeImap([])
    verify_login('me@gmail.com', 'app-password', imap_factory=fake)
    assert ('login', 'me@gmail.com') in fake.calls
    assert ('select', 'INBOX', True) in fake.calls
    assert fake.calls[-1] == ('logout',)


def test_verify_login_failure_raises_mail_client_error():
    with pytest.raises(MailClientError):
        verify_login('me@gmail.com', 'wrong', imap_factory=FakeImap([], is_login_failing=True))
