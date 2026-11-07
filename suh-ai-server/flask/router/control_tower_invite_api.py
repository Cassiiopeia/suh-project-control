"""관제소 프로젝트 디스코드 초대 API (nginx API 키 보호): POST /control/projects/<id>/invite
있으면 그대로, 없으면 발급, ?regenerate=1 이면 이전 초대 삭제 후 새로 발급 (링크 조회는 /control/manage invite_url)"""
from __future__ import annotations

from datetime import datetime, timezone

from flask import Blueprint, jsonify, request

from service.audit_service import AuditAction, AuditCategory
from service.control_tower.discord_invites import InviteError, ensure_project_invite
from service.control_tower.manage_view import load_manage_context
from service.control_tower.runtime import get_runtime
from util.audit_helper import audited, set_audit_detail

# 다시 만들기 쿼리 값 (?regenerate=1)
REGENERATE_QUERY_TRUE_VALUES = ("1", "true")


def register_invite_api(blueprint: Blueprint) -> None:
    blueprint.add_url_rule("/control/projects/<project_id>/invite", "control_project_invite", _create_invite,
                           methods=["POST"])


@audited(AuditCategory.CONTROL_TOWER, AuditAction.CONTROL_PROJECT_INVITE)
def _create_invite(project_id: str):
    """초대 발급: 런타임·디스코드 설정 > 프로젝트 확인 > 발급(또는 기존) > {url, code, created_at}"""
    runtime = get_runtime()
    if runtime is None:
        return jsonify({"error": "unavailable"}), 503
    discord_client = runtime.discord_client_provider() if runtime.discord_client_provider else None
    if discord_client is None or not runtime.guild_id:
        return jsonify({"error": "discord_not_configured"}), 503
    if not load_manage_context(runtime).is_known_project(project_id):
        return jsonify({"error": "unknown_project"}), 404

    should_regenerate = request.args.get("regenerate", "").lower() in REGENERATE_QUERY_TRUE_VALUES
    try:
        invite = ensure_project_invite(discord_client, runtime.store, project_id, should_regenerate,
                                       datetime.now(timezone.utc))
    except InviteError as error:
        body = {"error": error.code}
        if error.discord_status_code is not None:
            body["discord_status"] = error.discord_status_code
        return jsonify(body), error.status_code
    set_audit_detail({"project_id": project_id, "is_regenerated": should_regenerate, "code": invite.invite_code})
    return jsonify({"url": invite.url, "code": invite.invite_code, "created_at": invite.created_at.isoformat()})
