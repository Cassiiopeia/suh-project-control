"""
Gmail Claude 로그인 메일 조회: IMAP 읽기 전용 > 새 매직링크 메일 1건
메일함 상태(읽음·삭제·이동)는 바꾸지 않음
"""
import email
import email.utils
import html as html_entities
import imaplib
import logging
import re
from dataclasses import dataclass
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

GMAIL_IMAP_HOST = "imap.gmail.com"
# 로그인 메일 발신 도메인 2개: 현재 mail.anthropic.com, claude.com 계열 이전 대비 (부분 일치 검색)
LOGIN_MAIL_SENDER_DOMAINS = ("anthropic.com", "claude.com")
# 매직링크: magic-link 뒤 경로·쿼리 형태 무관 + #토큰 필수 (#144, #190)
# 예: magic-link#토큰 / magic-link?client=...#토큰 / magic-link/android#토큰
MAGIC_LINK_PATTERN = re.compile(r'href=["\'](https://claude\.ai/magic-link[^"\'#\s]*#[^"\'\s]+)["\']')
# 인식 실패 로그용 claude.ai 링크 (토큰 제외 경로만)
CLAUDE_LINK_PATH_PATTERN = re.compile(r'href=["\']https://claude\.ai(/[^"\'#?\s]*)')
# 최신 메일부터 확인할 개수 (claude.com 마케팅 메일 섞임 대비)
RECENT_MAIL_COUNT = 5
# IMAP 소켓 타임아웃 (초, 반쯤 끊긴 연결에서 작업이 running 에 갇히지 않게)
IMAP_TIMEOUT_SECONDS = 30

# 인식 실패 로그를 이미 남긴 Message-ID (프로세스 수명 동안 유지)
_unrecognized_message_ids = set()


class MailClientError(Exception):
    """IMAP 접속·인증·조회 실패"""


@dataclass
class MagicLinkMail:
    message_id: str
    received_at: datetime
    magic_link: str


def extract_magic_link(html: str):
    """메일 HTML > 매직링크 원문 (추적 링크 제외, 없으면 None)"""
    found = MAGIC_LINK_PATTERN.search(html or "")
    # href 속성값의 HTML 엔티티(&amp; 등) > 실제 주소
    return html_entities.unescape(found.group(1)) if found else None


def describe_claude_link_paths(html: str) -> str:
    """메일 HTML > claude.ai 링크 경로 목록 (토큰·쿼리 제외, 형식 변경 파악용)"""
    paths = sorted(set(CLAUDE_LINK_PATH_PATTERN.findall(html or "")))
    return ",".join(paths) or "none"


def verify_login(address, app_password, imap_factory=imaplib.IMAP4_SSL):
    """IMAP 로그인 + 받은편지함 읽기 전용 열기 (계정 등록 전 확인, 실패 시 MailClientError)"""
    try:
        mailbox = imap_factory(GMAIL_IMAP_HOST, timeout=IMAP_TIMEOUT_SECONDS)
        mailbox.login(address, app_password)
    except (imaplib.IMAP4.error, OSError) as error:
        raise MailClientError(f"imap login failed: {type(error).__name__}") from error
    try:
        mailbox.select("INBOX", readonly=True)
    except (imaplib.IMAP4.error, OSError) as error:
        raise MailClientError(f"imap select failed: {type(error).__name__}") from error
    finally:
        try:
            mailbox.logout()
        except (imaplib.IMAP4.error, OSError):
            pass


def find_new_magic_link_mail(address, app_password, accept_after: datetime,
                             processed_message_ids: set, imap_factory=imaplib.IMAP4_SSL):
    """accept_after 이후 수신 + 미처리 메일 중 최신 1건 (없으면 None)"""
    try:
        mailbox = imap_factory(GMAIL_IMAP_HOST, timeout=IMAP_TIMEOUT_SECONDS)
        mailbox.login(address, app_password)
    except (imaplib.IMAP4.error, OSError) as error:
        raise MailClientError(f"imap login failed: {type(error).__name__}") from error
    try:
        mailbox.select("INBOX", readonly=True)
        # SINCE 는 날짜 단위·시간대 불확실 > 하루 앞당김 (정확한 비교는 received_at)
        since_date = (accept_after - timedelta(days=1)).strftime("%d-%b-%Y")
        mail_ids = mailbox.search(None, *_build_sender_criteria(), "SINCE", since_date)[1][0].split()
        for mail_id in reversed(mail_ids[-RECENT_MAIL_COUNT:]):
            message = email.message_from_bytes(mailbox.fetch(mail_id, "(BODY.PEEK[])")[1][0][1])
            # Message-ID 없으면 IMAP id 로 대체
            message_id = message.get("Message-ID") or str(mail_id)
            received_at = email.utils.parsedate_to_datetime(message["Date"])
            if message_id in processed_message_ids or received_at < accept_after:
                continue
            mail = _to_magic_link_mail(message, message_id, received_at)
            if mail is not None:
                return mail
        return None
    except (imaplib.IMAP4.error, OSError) as error:
        raise MailClientError(f"imap search failed: {type(error).__name__}") from error
    finally:
        try:
            mailbox.logout()
        except (imaplib.IMAP4.error, OSError):
            pass


def _build_sender_criteria():
    """발신 도메인 n개 > IMAP 검색 조건 (OR FROM a FROM b)"""
    criteria = []
    for sender_domain in LOGIN_MAIL_SENDER_DOMAINS:
        criteria += ["FROM", sender_domain]
    return ["OR"] * (len(LOGIN_MAIL_SENDER_DOMAINS) - 1) + criteria


def _to_magic_link_mail(message, message_id, received_at):
    """메일 > MagicLinkMail (매직링크 없으면 링크 경로 로그 후 None)"""
    html_bodies = [part.get_payload(decode=True).decode(errors="ignore")
                   for part in message.walk() if part.get_content_type() == "text/html"]
    for html_body in html_bodies:
        magic_link = extract_magic_link(html_body)
        if magic_link:
            return MagicLinkMail(message_id, received_at, magic_link)
    # 링크 형식 변경 감지 (메일 1건당 1회 기록, 5초 폴링 반복 방지)
    if message_id in _unrecognized_message_ids:
        return None
    _unrecognized_message_ids.add(message_id)
    logger.warning("[claude login] magic link not recognized : message=%s claude_paths=%s",
                   message_id, describe_claude_link_paths("".join(html_bodies)))
    return None
