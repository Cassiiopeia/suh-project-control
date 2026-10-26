"""
매직링크 > 헤드리스 Chromium > 화면의 6자리 로그인 코드
링크는 1회용이라 열면 소모됨, 코드 못 찾으면 화면 캡처 저장
"""
import logging
import os
import re
import time

from config.claude_login_config import CODE_SEARCH_TIMEOUT_SECONDS, PLAYWRIGHT_BROWSERS_DIRECTORY

logger = logging.getLogger(__name__)

# Windows 서버: 배포 스크립트가 설치한 Chromium 위치 고정 (서비스 계정이 달라도 동일 경로)
if os.name == "nt":
    os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", PLAYWRIGHT_BROWSERS_DIRECTORY)

LOGIN_CODE_PATTERN = re.compile(r"(?<!\d)(\d{6})(?!\d)")
# 코드 화면 머리글: "인증 코드를 사용하여 계속하기"
LOGIN_CODE_LABEL = "인증 코드"
PAGE_TEXT_RETRY_SECONDS = 0.5
PAGE_GOTO_TIMEOUT_MILLISECONDS = 30000
# Cloudflare 봇 판정 회피: navigator.webdriver 끄기 + UA 의 HeadlessChrome 표식 제거 (2026-10-26 실측, 둘 다 필요)
BROWSER_LAUNCH_ARGS = ["--disable-blink-features=AutomationControlled"]
HEADLESS_USER_AGENT_MARKER = "HeadlessChrome"


class BrowserClientError(Exception):
    """브라우저 실행·페이지 이동 실패"""


class LoginCodeNotFoundError(Exception):
    """페이지는 열렸으나 6자리 코드 없음 (만료·차단 화면 등)"""


def extract_login_code(page_text: str):
    """페이지 텍스트 > 6자리 코드 ("인증 코드" 이후 우선, 없으면 None)"""
    text = page_text or ""
    label_index = text.find(LOGIN_CODE_LABEL)
    if label_index >= 0:
        found = LOGIN_CODE_PATTERN.search(text, label_index)
        if found:
            return found.group(1)
    found = LOGIN_CODE_PATTERN.search(text)
    return found.group(1) if found else None


def to_regular_chrome_user_agent(headless_user_agent: str) -> str:
    """헤드리스 UA > 같은 버전 일반 Chrome UA"""
    return headless_user_agent.replace(HEADLESS_USER_AGENT_MARKER, "Chrome")


def read_login_code(magic_link: str, screenshot_path: str) -> str:
    """매직링크 열기 > 최대 15초 동안 코드 탐색 > 코드 (실패 시 캡처 후 예외)"""
    from playwright.sync_api import Error as PlaywrightError, sync_playwright

    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True, args=BROWSER_LAUNCH_ARGS)
            try:
                user_agent = to_regular_chrome_user_agent(browser.new_page().evaluate("navigator.userAgent"))
                # 새 컨텍스트: 쿠키 없음, 한국어 화면 (코드 머리글 탐색 기준)
                page = browser.new_context(locale="ko-KR", user_agent=user_agent).new_page()
                page.goto(magic_link, timeout=PAGE_GOTO_TIMEOUT_MILLISECONDS)
                deadline = time.monotonic() + CODE_SEARCH_TIMEOUT_SECONDS
                while time.monotonic() < deadline:
                    login_code = extract_login_code(page.inner_text("body"))
                    if login_code:
                        return login_code
                    time.sleep(PAGE_TEXT_RETRY_SECONDS)
                page.screenshot(path=screenshot_path)
                logger.warning("[claude login] code not found on page : %s", page.url.split("#")[0])
                raise LoginCodeNotFoundError("login code not found")
            finally:
                browser.close()
    except PlaywrightError as error:
        raise BrowserClientError(f"browser failed: {type(error).__name__}") from error
