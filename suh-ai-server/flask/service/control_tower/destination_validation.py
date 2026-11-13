"""관제소 받을 곳 입력 규칙: 종류 선택지(채널 종류 단일 원본), 추가 요청 검증, 화면·응답용 항목 변환
종류 = dispatch가 받을 곳을 찾는 채널 종류 (to_channel_kind 결과값, info 이벤트는 status로 합쳐져 선택지에 없음)"""
from __future__ import annotations

from dataclasses import dataclass, field

from service.control_tower.destination_delivery import is_destination_url_supported
from service.control_tower.destination_store import Destination
from service.control_tower.overview import iso_text
from service.control_tower.registry_models import PROJECT_CHANNEL_KINDS

# 받을 곳 이름 최대 길이 (글자 수, 앞뒤 공백 제외)
DESTINATION_LABEL_MAX_LENGTH = 40
# 받을 곳 URL 최대 길이 (글자 수)
DESTINATION_URL_MAX_LENGTH = 2048


@dataclass(frozen=True)
class NewDestination:
    """검증 통과한 추가 요청 (url은 원문 > repr 제외)"""
    kind: str
    label: str
    url: str = field(repr=False)


def destination_kind_choices(store, project_id: str) -> tuple[str, ...]:
    """프로젝트 받을 곳 종류 선택지: 프로젝트 채널 기본 5종(planner·앱 이벤트·attention 공용) + 사용자 정의 종류(이름순)"""
    return PROJECT_CHANNEL_KINDS + tuple(sorted(store.list_event_kind_names_of_project(project_id)))


def parse_new_destination(payload, kind_choices: tuple[str, ...]) -> tuple[NewDestination | None, list[str]]:
    """추가 요청 본문 > (값, 잘못된 칸 목록) (칸 3개: kind 선택지 안, label 1~40자, url Apprise 해석 가능)"""
    body = payload if isinstance(payload, dict) else {}
    kind, label, url = body.get("kind"), body.get("label"), body.get("url")
    label = label.strip() if isinstance(label, str) else None
    url = url.strip() if isinstance(url, str) else None
    invalid_fields = []
    if not isinstance(kind, str) or kind not in kind_choices:
        invalid_fields.append("kind")
    if not label or len(label) > DESTINATION_LABEL_MAX_LENGTH:
        invalid_fields.append("label")
    if not url or len(url) > DESTINATION_URL_MAX_LENGTH or not is_destination_url_supported(url):
        invalid_fields.append("url")
    if invalid_fields:
        return None, invalid_fields
    return NewDestination(kind, label, url), []


def destination_entry(destination: Destination) -> dict:
    """받을 곳 1개 > 화면·응답 dict (URL 원문·암호문 없음, 힌트만)"""
    return {"destination_id": destination.destination_id, "kind": destination.kind, "label": destination.label,
            "url_hint": destination.url_hint, "is_enabled": destination.is_enabled,
            "last_result": destination.last_result, "last_sent_at": iso_text(destination.last_sent_at)}


def destination_audit_detail(destination: Destination) -> dict:
    """감사 상세 (URL 없음: project_id·kind·label·url_hint + destination_id)"""
    return {"destination_id": destination.destination_id, "project_id": destination.project_id,
            "kind": destination.kind, "label": destination.label, "url_hint": destination.url_hint}
