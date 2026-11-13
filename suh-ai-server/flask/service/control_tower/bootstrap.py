"""관제소 기동 조립: 저장소 > 디스코드 클라이언트 > 발송기(+ 받을 곳) > 심박 클라이언트 > 폴러 시작 > 런타임 등록 > 기본 썸네일 1회 > 디스코드 동기화 1회
env 없는 구성 요소는 None으로 두고 나머지만 동작 (토큰 없음 > 발송 생략, Worker 설정 없음 > 외부 결과·심박 없음)
"""
from __future__ import annotations

import logging
import os
import threading
from typing import Mapping

from config.control_tower_config import (
    DATABASE_PATH, DISCORD_BOT_TOKEN_ENV, DISCORD_GUILD_ID_ENV, HMAC_SECRET_ENV, REGISTRY_PATH, WORKER_URL_ENV,
)
from service.control_tower.app_attention_ingest import AppAttentionIngest
from service.control_tower.destination_delivery import DestinationDeliverer
from service.control_tower.discord_client import DiscordClient
from service.control_tower.discord_invite_attribution import InviteAttributionStep
from service.control_tower.discord_sync import DISCORD_SYNC_LOCK, sync_discord
from service.control_tower.event_dispatcher import EventDispatcher
from service.control_tower.heartbeat_client import HeartbeatClient
from service.control_tower.poller import ControlTowerPoller
from service.control_tower.poller_app_attention import AppAttentionStep, is_any_project_service_down
from service.control_tower.project_icon_seed import seed_default_project_icons
from service.control_tower.registry_overrides import load_effective_registry
from service.control_tower.runtime import ControlTowerRuntime, set_runtime
from service.control_tower.store import ControlTowerStore
from util.background_runner import run_in_background

logger = logging.getLogger(__name__)

# .env: 공개 status 페이지 주소 (임베드 기본 링크)
STATUS_PAGE_URL_ENV = "CONTROL_TOWER_STATUS_PAGE_URL"
DEFAULT_STATUS_PAGE_URL = "https://status.suhsaechan.kr"


def start_control_tower(environ: Mapping[str, str] = os.environ, database_path: str = DATABASE_PATH,
                        registry_path: str = REGISTRY_PATH) -> ControlTowerRuntime:
    """관제소 기동: 구성 요소 조립 > 폴러 데몬 스레드 시작 > 런타임 등록 > (토큰 있으면) 디스코드 동기화 스레드"""
    store = ControlTowerStore(database_path)
    store.initialize()

    discord_client = _build_discord_client(environ)
    dispatcher = EventDispatcher(
        store=store,
        discord_client_provider=lambda: discord_client,
        status_page_url=environ.get(STATUS_PAGE_URL_ENV) or DEFAULT_STATUS_PAGE_URL,
        destination_deliverer=DestinationDeliverer(store, run_in_background, environ),
    )
    invite_attribution = InviteAttributionStep(discord_client, store) if discord_client is not None else None
    # 앱 확인할 일: 프로젝트 서비스 중 하나라도 down이면 앱 연동 끊김 알림 생략 (서비스 장애에 묻음)
    # 수집기 <-> 폴러 상호 참조: 람다는 호출 시점에 poller를 찾음 (아래에서 생성)
    app_attention_ingest = AppAttentionIngest(
        store, dispatcher, lambda: poller.current_registry(),
        lambda project_id: is_any_project_service_down(
            poller.current_registry(), poller.snapshot().states, project_id))
    poller = ControlTowerPoller(registry_path, store, dispatcher, _build_heartbeat_client(environ),
                                environ=environ, invite_attribution=invite_attribution,
                                app_attention_step=AppAttentionStep(store, app_attention_ingest))

    runtime = ControlTowerRuntime(registry_provider=poller.current_registry, store=store, dispatcher=dispatcher,
                                  poller=poller, file_registry_provider=poller.current_file_registry,
                                  discord_client_provider=lambda: discord_client,
                                  guild_id=environ.get(DISCORD_GUILD_ID_ENV) or None,
                                  app_attention_ingest=app_attention_ingest)
    set_runtime(runtime)
    poller.start()
    # 기본 썸네일 가져오기 (네트워크 호출이라 별도 스레드, 실패는 기록만)
    threading.Thread(target=_seed_default_icons_once, args=(registry_path, environ, store),
                     daemon=True, name="control-tower-icon-seed").start()

    if discord_client is not None:
        threading.Thread(target=_sync_discord_once, args=(registry_path, environ, discord_client, store),
                         daemon=True, name="control-tower-discord-sync").start()
    return runtime


def _build_discord_client(environ: Mapping[str, str]) -> DiscordClient | None:
    """봇 토큰 + 길드 ID 둘 다 있을 때만 클라이언트"""
    bot_token = environ.get(DISCORD_BOT_TOKEN_ENV)
    guild_id = environ.get(DISCORD_GUILD_ID_ENV)
    if not bot_token or not guild_id:
        logger.warning("[control-tower bootstrap] discord disabled : bot token or guild id is not set")
        return None
    return DiscordClient(bot_token, guild_id)


def _build_heartbeat_client(environ: Mapping[str, str]) -> HeartbeatClient | None:
    """Worker 주소 + 서명 비밀키 둘 다 있을 때만 클라이언트"""
    worker_url = environ.get(WORKER_URL_ENV)
    secret = environ.get(HMAC_SECRET_ENV)
    if not worker_url or not secret:
        logger.warning("[control-tower bootstrap] heartbeat disabled : worker url or secret is not set")
        return None
    return HeartbeatClient(worker_url, secret)


def _seed_default_icons_once(registry_path: str, environ: Mapping[str, str], store: ControlTowerStore) -> None:
    """기동 시 기본 썸네일 1회: 실효 등록 정보의 icon_source_url 중 아직 없는 것만"""
    try:
        seed_default_project_icons(load_effective_registry(registry_path, environ, store), store)
    except Exception as error:
        logger.warning("[control-tower icon seed] startup seed failed : %s", type(error).__name__)


def _sync_discord_once(registry_path: str, environ: Mapping[str, str], discord_client: DiscordClient,
                       store: ControlTowerStore) -> None:
    """기동 시 디스코드 구조 동기화 1회: 실효 등록 정보 기준 (실패는 기록만)"""
    try:
        registry = load_effective_registry(registry_path, environ, store)
        with DISCORD_SYNC_LOCK:  # 관리자 화면 버튼과 동시 실행 방지
            sync_discord(registry, discord_client, store, environ[DISCORD_GUILD_ID_ENV])
    except Exception as error:
        logger.warning("[control-tower discord sync] startup sync failed : %s", type(error).__name__)
