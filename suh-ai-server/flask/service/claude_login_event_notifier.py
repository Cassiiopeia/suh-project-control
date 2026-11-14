"""Claude 로그인 코드 알림: 발급·열람 공통 필드 구성 > 관제소 프로젝트 이벤트 발송 (코드·Gmail 주소 제외)"""
from config import claude_login_config as config
from service.control_tower.project_event_sender import send_project_event


def notify_claude_code_event(title: str, dedupe_key: str, display_name: str | None,
                             client_ip: str | None, user_agent: str | None) -> bool:
    """알림 1건: 계정 이름·IP·브라우저 필드 구성 > 발송 (실패해도 로그인 흐름 영향 없음)"""
    return send_project_event(
        config.CONTROL_TOWER_PROJECT_ID, config.CONTROL_TOWER_EVENT_KIND, title,
        fields=[('계정', display_name), ('IP', client_ip),
                ('브라우저', (user_agent or '')[:config.EVENT_USER_AGENT_MAX_LENGTH])],
        dedupe_key=dedupe_key)
