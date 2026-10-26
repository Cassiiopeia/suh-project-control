"""test_claude_login_browser_client.py — 매직링크 페이지 텍스트 > 6자리 코드"""
from service.claude_login_browser_client import extract_login_code, to_regular_chrome_user_agent


def test_user_agent_drops_headless_marker():
    headless_user_agent = ('Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 '
                           '(KHTML, like Gecko) HeadlessChrome/140.0.0.0 Safari/537.36')
    assert 'HeadlessChrome' not in to_regular_chrome_user_agent(headless_user_agent)
    assert 'Chrome/140.0.0.0' in to_regular_chrome_user_agent(headless_user_agent)


def test_extract_code_from_real_page_text():
    page_text = ('인증 코드를 사용하여 계속하기\n처음 로그인을 시도한 곳에 이 인증 코드를 입력하세요\n'
                 '027696\n코드 복사\n대신 여기에서 로그인하세요')
    assert extract_login_code(page_text) == '027696'


def test_extract_code_prefers_number_after_label():
    page_text = '2026-10 123456 공지\n인증 코드를 사용하여 계속하기\n654321\n코드 복사'
    assert extract_login_code(page_text) == '654321'


def test_extract_code_none_when_absent():
    assert extract_login_code('링크가 만료되었습니다. 다시 로그인하세요') is None
