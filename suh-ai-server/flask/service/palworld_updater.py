"""
Palworld 서버 바이너리 업데이트
SteamCMD로 새 빌드 감지(appmanifest vs app_info_print) 및 업데이트 실행.
백업 → 서비스 중지 → app_update → 서비스 시작. 진행 상태/출력은 전역 링버퍼로 관리.
"""
import os
import re
import json
import time
import logging
import threading
import subprocess
from collections import deque
from datetime import datetime

from config.palworld_config import (
    STEAMCMD_EXE, PALWORLD_APP_ID, APP_MANIFEST_PATH,
    UPDATE_CHECK_INTERVAL_SEC, UPDATE_LOG_MAXLEN, UPDATE_TIMEOUT_SEC,
    UPDATE_LOG_FILE, UPDATE_LAST_FILE,
)
from service import audit_service
from service.audit_service import AuditCategory, AuditAction

logger = logging.getLogger(__name__)

_lock = threading.Lock()
_state = {
    'status': 'idle',      # idle | running | done | failed
    'step': None,          # backup | stop | download | start
    'trigger': None,       # manual | auto
    'error': None,
    'started_at': None,
    'finished_at': None,
}
_log = deque(maxlen=UPDATE_LOG_MAXLEN)
_version = {
    'local_build': None,
    'remote_build': None,
    'update_available': None,   # True | False | None(판단 불가)
    'checked_at': None,
}


def _append_log(text):
    """진행 로그 한 줄을 메모리 링버퍼 + 디스크 파일(UPDATE_LOG_FILE)에 함께 기록한다.
    파일 기록 실패는 진행 자체를 막지 않도록 warning만 남긴다."""
    _log.append(text)
    try:
        os.makedirs(os.path.dirname(UPDATE_LOG_FILE), exist_ok=True)
        with open(UPDATE_LOG_FILE, 'a', encoding='utf-8') as f:
            f.write(text + '\n')
    except OSError as e:
        logger.warning(f'업데이트 로그 파일 기록 실패: {e}')


def _load_last_update():
    if not os.path.exists(UPDATE_LAST_FILE):
        return None
    try:
        with open(UPDATE_LAST_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return data if isinstance(data, dict) else None
    except (OSError, ValueError) as e:
        logger.warning(f'마지막 업데이트 정보 읽기 실패: {e}')
        return None


def _save_last_update(data):
    try:
        os.makedirs(os.path.dirname(UPDATE_LAST_FILE), exist_ok=True)
        with open(UPDATE_LAST_FILE, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False)
    except OSError as e:
        logger.warning(f'마지막 업데이트 정보 저장 실패: {e}')


def get_local_buildid():
    """설치된 서버 빌드 ID — steamapps/appmanifest_2394010.acf에서 파싱"""
    try:
        with open(APP_MANIFEST_PATH, 'r', encoding='utf-8', errors='replace') as f:
            m = re.search(r'"buildid"\s+"(\d+)"', f.read())
        return m.group(1) if m else None
    except OSError:
        return None


def parse_remote_buildid(app_info_output):
    """steamcmd app_info_print 출력에서 public 브랜치 buildid 추출"""
    m = re.search(r'"public"\s*\{[^{}]*?"buildid"\s*"(\d+)"', app_info_output)
    return m.group(1) if m else None


def get_remote_buildid():
    """Steam의 최신 public 빌드 ID 조회 (steamcmd, 최대 3분)"""
    try:
        result = subprocess.run(
            [STEAMCMD_EXE, '+login', 'anonymous',
             '+app_info_update', '1', '+app_info_print', PALWORLD_APP_ID, '+quit'],
            capture_output=True, text=True, errors='replace', timeout=180
        )
        return parse_remote_buildid(result.stdout or '')
    except (OSError, subprocess.TimeoutExpired) as e:
        logger.warning(f'원격 빌드 조회 실패: {e}')
        return None


def check_for_update():
    local = get_local_buildid()
    remote = get_remote_buildid()
    available = (local != remote) if (local and remote) else None
    _version.update({
        'local_build': local, 'remote_build': remote,
        'update_available': available,
        'checked_at': datetime.now().isoformat(timespec='seconds'),
    })
    return dict(_version)


def get_state():
    with _lock:
        state = dict(_state)
    state.update(_version)
    state['log'] = list(_log)
    state['last_update'] = _load_last_update()
    return state


def start_update(trigger, actor_ip):
    """업데이트 시작. 이미 진행 중이면 False. 감사 기록은 여기서(트리거·행위자 포함)."""
    with _lock:
        if _state['status'] == 'running':
            return False
        _state.update({
            'status': 'running', 'step': 'backup', 'trigger': trigger,
            'error': None, 'finished_at': None,
            'started_at': datetime.now().isoformat(timespec='seconds'),
        })
    _log.clear()
    started_at = _state['started_at']
    _append_log(f'=== {started_at} 업데이트 시작 (trigger={trigger}) ===')
    _append_log(f'[update] 서버 업데이트 시작 (trigger={trigger})')
    audit_service.record(
        AuditCategory.PALWORLD, AuditAction.SERVER_UPDATE, actor_ip,
        {'trigger': trigger, 'local_build': _version.get('local_build'),
         'remote_build': _version.get('remote_build')})
    threading.Thread(target=_run_update, daemon=True).start()
    return True


def _set_step(step):
    with _lock:
        _state['step'] = step


def _run_steamcmd_update():
    """steamcmd app_update 실행 — 출력을 라인 단위로 링버퍼에 스트리밍"""
    proc = subprocess.Popen(
        [STEAMCMD_EXE, '+login', 'anonymous',
         '+app_update', PALWORLD_APP_ID, 'validate', '+quit'],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, errors='replace', bufsize=1
    )
    timed_out = threading.Event()

    def _kill_stalled():
        timed_out.set()
        proc.kill()

    # 읽기 루프 자체가 EOF까지 블록되므로, 벽시계 기준 워치독이 멈춘 프로세스를 강제 종료해
    # except 경로(서비스 복구 재시작)가 반드시 실행되게 한다.
    watchdog = threading.Timer(UPDATE_TIMEOUT_SEC, _kill_stalled)
    watchdog.start()
    success_seen = False
    try:
        for line in proc.stdout:
            line = line.strip()
            if line:
                _append_log(line)
                if 'Success!' in line:
                    success_seen = True
        code = proc.wait()
    finally:
        watchdog.cancel()
    if timed_out.is_set():
        raise RuntimeError(f'steamcmd 시간 초과({UPDATE_TIMEOUT_SEC}초) — 프로세스 강제 종료')
    # steamcmd는 성공해도 0이 아닌 코드를 내는 경우가 있어 출력의 Success!를 함께 본다
    if not success_seen and code != 0:
        raise RuntimeError(f'steamcmd 실패 (exit {code})')


def _run_update():
    from service.palworld_service import PalworldService  # 지연 임포트 (순환 방지)
    service = PalworldService()
    try:
        _set_step('backup')
        try:
            backup = service.create_backup()
            _append_log(f"[backup] 완료: {backup.get('name')}")
        except Exception as e:
            logger.warning(f'업데이트 전 백업 실패(계속 진행): {e}')
            _append_log(f'[backup] 실패 — 계속 진행: {e}')

        _set_step('stop')
        if service.get_service_state() == 'running':
            service.stop()
        _append_log('[stop] 서비스 중지 완료')

        _set_step('download')
        _run_steamcmd_update()
        _append_log('[download] 새 빌드 설치 완료')

        _set_step('start')
        service.start()
        _append_log('[start] 서비스 시작 완료')

        # 로컬 빌드 갱신 → 배지가 "최신 상태"로 돌아온다
        local = get_local_buildid()
        remote = _version.get('remote_build')
        _version.update({
            'local_build': local,
            'update_available': (local != remote) if (local and remote) else None,
        })
        finished_at = datetime.now().isoformat(timespec='seconds')
        with _lock:
            _state.update({'status': 'done', 'step': None, 'finished_at': finished_at})
        _save_last_update({'finished_at': finished_at, 'build': local})
        logger.info('팰월드 서버 업데이트 완료')
    except Exception as e:
        logger.error(f'팰월드 서버 업데이트 실패: {e}')
        _append_log(f'[error] {e}')
        # 실패해도 서버를 방치하지 않는다 — 구버전으로라도 재기동 시도
        try:
            if service.get_service_state() != 'running':
                service.start()
                _append_log('[recover] 서비스 재시작(기존 버전) 완료')
        except Exception as recover_error:
            _append_log(f'[recover] 서비스 재시작 실패: {recover_error}')
        with _lock:
            _state.update({'status': 'failed', 'step': None, 'error': str(e),
                           'finished_at': datetime.now().isoformat(timespec='seconds')})


def _count_players(service):
    """자동 업데이트 판단용 접속자 수. 판단 불가(REST 다운 등)면 0으로 간주 —
    서버가 비정상인 상황이면 어차피 업데이트가 이득이다."""
    try:
        status = service.get_status()
        if status['state'] != 'running':
            return 0
        metrics = status.get('metrics') or {}
        n = metrics.get('currentplayernum')
        return int(n) if n is not None else 0
    except Exception:
        return 0


def auto_check_loop(interval_sec=UPDATE_CHECK_INTERVAL_SEC):
    """새 빌드 자동 감지 루프 (데몬 스레드). 감지 시 접속자 0명이면 자동 업데이트."""
    from service.palworld_service import PalworldService
    service = PalworldService()
    while True:
        try:
            info = check_for_update()
            if info['update_available'] and get_state()['status'] != 'running':
                players = _count_players(service)
                if players == 0:
                    logger.info('새 빌드 감지 → 자동 업데이트 시작')
                    start_update('auto', 'system')
                else:
                    logger.info(f'새 빌드 감지, 접속자 {players}명 → 다음 주기에 재시도')
        except Exception as e:
            logger.warning(f'자동 업데이트 체크 실패: {e}')
        time.sleep(interval_sec)
