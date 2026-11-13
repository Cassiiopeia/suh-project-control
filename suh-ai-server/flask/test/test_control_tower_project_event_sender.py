"""내부 발송 함수 테스트: 런타임 없음·접수·거부·예외 모두 예외 없이 bool 반환"""
import logging
from types import SimpleNamespace
from unittest.mock import patch

from service.control_tower import project_event_sender as sender
from service.control_tower.event_dispatcher import EVENT_FIELD_VALUE_MAX_LENGTH

RUNTIME_GETTER = 'service.control_tower.project_event_sender.get_runtime'


class FakeDispatcher:
    def __init__(self, response=(202, {'accepted': True}), error=None):
        self.response = response
        self.error = error
        self.calls = []

    def accept_event(self, project_id, payload, now):
        self.calls.append((project_id, payload, now))
        if self.error:
            raise self.error
        return self.response


def runtime_with(dispatcher):
    return SimpleNamespace(dispatcher=dispatcher)


def test_returns_false_without_runtime():
    with patch(RUNTIME_GETTER, return_value=None):
        assert sender.send_project_event('p', 'k', 't') is False


def test_accepted_returns_true_and_builds_payload():
    dispatcher = FakeDispatcher()
    with patch(RUNTIME_GETTER, return_value=runtime_with(dispatcher)):
        is_sent = sender.send_project_event('p', 'k', '제목', fields=[('계정', 'a'), ('IP', None)],
                                            dedupe_key='d1', url='https://x')
    assert is_sent is True
    project_id, payload, _ = dispatcher.calls[0]
    assert project_id == 'p'
    assert payload['kind'] == 'k' and payload['title'] == '제목' and payload['severity'] == 'info'
    assert payload['fields'] == [{'name': '계정', 'value': 'a'}]  # None 값은 제외
    assert payload['dedupe_key'] == 'd1' and payload['url'] == 'https://x'


def test_deduplicated_accept_counts_as_success():
    dispatcher = FakeDispatcher(response=(202, {'deduplicated': True}))
    with patch(RUNTIME_GETTER, return_value=runtime_with(dispatcher)):
        assert sender.send_project_event('p', 'k', 't') is True


def test_rejected_returns_false_and_logs_warning(caplog):
    dispatcher = FakeDispatcher(response=(400, {'error': 'unknown_kind'}))
    with patch(RUNTIME_GETTER, return_value=runtime_with(dispatcher)), caplog.at_level(logging.WARNING):
        assert sender.send_project_event('p', 'k', 't') is False
    assert '[control-tower project event]' in caplog.text


def test_dispatcher_exception_returns_false_without_raising(caplog):
    dispatcher = FakeDispatcher(error=RuntimeError('boom'))
    with patch(RUNTIME_GETTER, return_value=runtime_with(dispatcher)), caplog.at_level(logging.WARNING):
        assert sender.send_project_event('p', 'k', 't') is False
    assert '[control-tower project event]' in caplog.text


def test_long_field_value_is_truncated_to_dispatcher_limit():
    dispatcher = FakeDispatcher()
    with patch(RUNTIME_GETTER, return_value=runtime_with(dispatcher)):
        sender.send_project_event('p', 'k', 't', fields=[('계정', 'x' * (EVENT_FIELD_VALUE_MAX_LENGTH + 50))])
    assert len(dispatcher.calls[0][1]['fields'][0]['value']) == EVENT_FIELD_VALUE_MAX_LENGTH
