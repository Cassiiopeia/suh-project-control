"""test_db_config.py"""
import os

from config.db_config import get_audit_database_url, apply_migrations, MIGRATIONS_DIR


def test_url_unset_returns_none(monkeypatch):
    monkeypatch.delenv('AUDIT_DATABASE_URL', raising=False)
    assert get_audit_database_url() is None


def test_url_set_returns_value(monkeypatch):
    monkeypatch.setenv('AUDIT_DATABASE_URL', 'postgresql://u:p@h:5430/d')
    assert get_audit_database_url() == 'postgresql://u:p@h:5430/d'


def test_apply_migrations_skips_without_url(monkeypatch):
    monkeypatch.delenv('AUDIT_DATABASE_URL', raising=False)
    assert apply_migrations() is False


def test_apply_migrations_swallows_db_errors(monkeypatch):
    # 존재하지 않는 호스트 → 연결 예외가 밖으로 새지 않고 False
    monkeypatch.setenv('AUDIT_DATABASE_URL', 'postgresql://u:p@127.0.0.1:1/no_db')
    assert apply_migrations() is False


def test_migration_file_is_parseable():
    from yoyo import read_migrations
    migrations = read_migrations(MIGRATIONS_DIR)
    assert len(migrations) >= 1


def test_migration_file_is_ascii_only():
    # yoyo Migration.load()가 encoding 미지정 open()을 쓰므로 (Windows cp949에서 깨짐)
    # 마이그레이션 SQL은 ASCII만 허용한다
    import glob
    for path in glob.glob(os.path.join(MIGRATIONS_DIR, '*.sql')):
        with open(path, encoding='ascii') as f:
            f.read()  # non-ASCII가 있으면 UnicodeDecodeError로 실패


def test_migration_loads_via_yoyo():
    from yoyo import read_migrations
    migration = read_migrations(MIGRATIONS_DIR)[0]
    migration.load()  # 실제 파싱 경로 — cp949 환경에서도 성공해야 한다
    assert migration.steps  # 스텝이 실제로 추출됨
