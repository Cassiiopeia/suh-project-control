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
