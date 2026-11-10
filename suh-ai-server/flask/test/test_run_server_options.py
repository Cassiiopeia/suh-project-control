"""test_run_server_options.py — waitress 실행 옵션: 프록시 IP 헤더 유지 (#186)"""
import ast
import os

RUN_PATH = os.path.join(os.path.dirname(__file__), '..', 'run.py')


def find_serve_keywords() -> dict:
    """run.py 의 serve(...) 호출 > {옵션 이름: 값}"""
    tree = ast.parse(open(RUN_PATH, encoding='utf-8').read())
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and getattr(node.func, 'id', None) == 'serve':
            return {keyword.arg: keyword.value for keyword in node.keywords}
    raise AssertionError('serve() call not found in run.py')


def test_serve_keeps_forwarded_headers_for_audit_ip():
    # waitress 3.x 기본값은 X-Forwarded-For 삭제 > 감사로그 IP 가 127.0.0.1 로만 남음
    keywords = find_serve_keywords()
    assert 'clear_untrusted_proxy_headers' in keywords
    assert isinstance(keywords['clear_untrusted_proxy_headers'], ast.Constant)
    assert keywords['clear_untrusted_proxy_headers'].value is False
