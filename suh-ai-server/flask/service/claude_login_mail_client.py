"""
Gmail Claude 로그인 메일 조회: IMAP 읽기 전용 > 새 매직링크 메일 1건
메일함 상태(읽음·삭제·이동)는 바꾸지 않음
"""
import email
import email.utils
import imaplib
import re
from dataclasses import dataclass
from datetime import datetime

GMAIL_IMAP_HOST = "imap.gmail.com"
# Anthropic 로그인 메일 발신 도메인
ANTHROPIC_SENDER_DOMAIN = "mail.anthropic.com"
MAGIC_LINK_PATTERN = re.compile(r'href="(https://claude\.ai/magic-link#[^"]+)"')
# 최신 메일부터 확인할 개수
RECENT_MAIL_COUNT = 3


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
    return found.group(1) if found else None


def find_new_magic_link_mail(address, app_password, accept_after: datetime,
                             processed_message_ids: set, imap_factory=imaplib.IMAP4_SSL):
    """accept_after 이후 수신 + 미처리 메일 중 최신 1건 (없으면 None)"""
    try:
        mailbox = imap_factory(GMAIL_IMAP_HOST)
        mailbox.login(address, app_password)
    except (imaplib.IMAP4.error, OSError) as error:
        raise MailClientError(f"imap login failed: {type(error).__name__}") from error
    try:
        mailbox.select("INBOX", readonly=True)
        since_date = accept_after.strftime("%d-%b-%Y")
        mail_ids = mailbox.search(None, "FROM", ANTHROPIC_SENDER_DOMAIN, "SINCE", since_date)[1][0].split()
        for mail_id in reversed(mail_ids[-RECENT_MAIL_COUNT:]):
            mail = _to_magic_link_mail(mail_id, mailbox.fetch(mail_id, "(BODY.PEEK[])")[1][0][1])
            if mail is None or mail.message_id in processed_message_ids:
                continue
            if mail.received_at >= accept_after:
                return mail
        return None
    except (imaplib.IMAP4.error, OSError) as error:
        raise MailClientError(f"imap search failed: {type(error).__name__}") from error
    finally:
        try:
            mailbox.logout()
        except (imaplib.IMAP4.error, OSError):
            pass


def _to_magic_link_mail(mail_id, raw_mail: bytes):
    """원본 메일 > MagicLinkMail (매직링크 없으면 None)"""
    message = email.message_from_bytes(raw_mail)
    for part in message.walk():
        if part.get_content_type() != "text/html":
            continue
        magic_link = extract_magic_link(part.get_payload(decode=True).decode(errors="ignore"))
        if magic_link:
            # Message-ID 없으면 IMAP id 로 대체
            message_id = message.get("Message-ID") or str(mail_id)
            received_at = email.utils.parsedate_to_datetime(message["Date"])
            return MagicLinkMail(message_id, received_at, magic_link)
    return None
