"""gbrain /admin 게이트 쿠키: 서명·만료·변조·토큰 교체"""
from service.gbrain_admin_gate import create_gate_cookie_value, is_gate_cookie_valid

ADMIN_TOKEN = 'a' * 40
NOW = 1_800_000_000


def test_발급한_쿠키는_만료_전_유효():
    cookie_value = create_gate_cookie_value(ADMIN_TOKEN, 60, now_epoch_seconds=NOW)
    assert is_gate_cookie_valid(ADMIN_TOKEN, cookie_value, now_epoch_seconds=NOW + 59)


def test_만료되면_무효():
    cookie_value = create_gate_cookie_value(ADMIN_TOKEN, 60, now_epoch_seconds=NOW)
    assert not is_gate_cookie_valid(ADMIN_TOKEN, cookie_value, now_epoch_seconds=NOW + 60)


def test_만료시각을_늘려_변조하면_무효():
    cookie_value = create_gate_cookie_value(ADMIN_TOKEN, 60, now_epoch_seconds=NOW)
    _, signature = cookie_value.split('.', 1)
    assert not is_gate_cookie_valid(ADMIN_TOKEN, f'{NOW + 99999}.{signature}', now_epoch_seconds=NOW)


def test_토큰을_바꾸면_기존_쿠키_무효():
    cookie_value = create_gate_cookie_value(ADMIN_TOKEN, 60, now_epoch_seconds=NOW)
    assert not is_gate_cookie_valid('b' * 40, cookie_value, now_epoch_seconds=NOW)


def test_토큰_쿠키_없거나_형식이_틀리면_무효():
    assert not is_gate_cookie_valid(None, 'x', now_epoch_seconds=NOW)
    assert not is_gate_cookie_valid(ADMIN_TOKEN, None, now_epoch_seconds=NOW)
    assert not is_gate_cookie_valid(ADMIN_TOKEN, 'no-dot', now_epoch_seconds=NOW)
    assert not is_gate_cookie_valid(ADMIN_TOKEN, 'abc.def', now_epoch_seconds=NOW)
