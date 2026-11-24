"""
팀 브레인 등록부: {GBRAIN_TEAM_ROOT}/team-brains.json (배포가 덮어쓰는 C:/AI/suh-ai-server 밖, 비밀값 없음)
항목 = 프로젝트 키·내부 포트·DB·쓰기 계정·만든 때 > 나머지(서비스 이름·폴더·공개 주소)는 이름 규칙으로 계산
"""
import json
import os
import tempfile
import threading
from datetime import datetime, timezone

from config import gbrain_server_config as config
from service.gbrain_instance import build_team_instance

REGISTRY_FILE_NAME = 'team-brains.json'
REGISTRY_VERSION = 1


class GbrainTeamRegistryError(Exception):
    """등록부 파일 손상 (조용히 비우면 포트가 겹치므로 실패로 알림)"""


class GbrainTeamRegistry:
    def __init__(self, team_root=None):
        # None: 호출 시점의 GBRAIN_TEAM_ROOT (테스트 monkeypatch 반영)
        self._team_root = team_root
        self._lock = threading.Lock()

    @property
    def team_root(self) -> str:
        return self._team_root or config.GBRAIN_TEAM_ROOT

    @property
    def registry_path(self) -> str:
        return os.path.join(self.team_root, REGISTRY_FILE_NAME)

    # ---------- 조회 ----------
    def list_entries(self) -> list:
        """등록된 팀 브레인 (프로젝트 키 순), 파일 없으면 빈 목록"""
        try:
            with open(self.registry_path, encoding='utf-8') as registry_stream:
                registry = json.load(registry_stream)
        except FileNotFoundError:
            return []
        except (OSError, ValueError) as error:
            raise GbrainTeamRegistryError(f'team brain registry unreadable : {type(error).__name__}')
        entries = registry.get('brains') if isinstance(registry, dict) else None
        if not isinstance(entries, list):
            raise GbrainTeamRegistryError('team brain registry has no brains list')
        return sorted((entry for entry in entries if isinstance(entry, dict) and entry.get('project')),
                      key=lambda entry: entry['project'])

    def find_entry(self, project: str):
        return next((entry for entry in self.list_entries() if entry['project'] == project), None)

    def list_instances(self) -> list:
        return [self.to_instance(entry) for entry in self.list_entries()]

    def find_instance(self, project: str):
        entry = self.find_entry(project)
        return self.to_instance(entry) if entry else None

    @staticmethod
    def to_instance(entry: dict):
        return build_team_instance(entry['project'], int(entry['port']), entry['database_name'], entry['writer_role'])

    # ---------- 변경 ----------
    def register(self, project: str, database_name: str, writer_role: str) -> dict:
        """등록 (이미 있으면 그대로 반환: 포트 유지), 새 항목은 빈 포트 중 가장 작은 값"""
        with self._lock:
            entries = self.list_entries()
            existing_entry = next((entry for entry in entries if entry['project'] == project), None)
            if existing_entry:
                return existing_entry
            new_entry = {
                'project': project,
                'port': self._allocate_port(entries),
                'database_name': database_name,
                'writer_role': writer_role,
                'created_at': datetime.now(timezone.utc).isoformat(timespec='seconds'),
            }
            self._write_entries(entries + [new_entry])
            return new_entry

    def preview_entry(self, project: str, database_name: str, writer_role: str) -> dict:
        """dry_run 용: 등록돼 있으면 그 항목, 아니면 받게 될 포트로 만든 항목 (파일에 쓰지 않음, is_registered 표시)"""
        entries = self.list_entries()
        existing_entry = next((entry for entry in entries if entry['project'] == project), None)
        if existing_entry:
            return {**existing_entry, 'is_registered': True}
        return {'project': project, 'port': self._allocate_port(entries), 'database_name': database_name,
                'writer_role': writer_role, 'created_at': None, 'is_registered': False}

    @staticmethod
    def _allocate_port(entries: list) -> int:
        used_ports = {int(entry['port']) for entry in entries if str(entry.get('port', '')).isdigit()}
        for port in range(config.GBRAIN_TEAM_PORT_FIRST, config.GBRAIN_TEAM_PORT_LAST + 1):
            if port not in used_ports:
                return port
        raise GbrainTeamRegistryError('no free team brain port')

    def _write_entries(self, entries: list) -> None:
        """임시 파일 > 교체 (쓰는 도중 실패해도 기존 등록부 유지)"""
        os.makedirs(self.team_root, exist_ok=True)
        registry = {'version': REGISTRY_VERSION, 'brains': sorted(entries, key=lambda entry: entry['project'])}
        file_descriptor, temporary_path = tempfile.mkstemp(dir=self.team_root, suffix='.tmp')
        try:
            with os.fdopen(file_descriptor, 'w', encoding='utf-8') as temporary_stream:
                json.dump(registry, temporary_stream, ensure_ascii=False, indent=2)
            os.replace(temporary_path, self.registry_path)
        except BaseException:
            if os.path.exists(temporary_path):
                os.remove(temporary_path)
            raise


gbrain_team_registry = GbrainTeamRegistry()
