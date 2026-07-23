"""Тесты backup_db (P-7): WAL-safe SQLite-бэкап, ротация, выбор движка."""

import sqlite3

import pytest

import scripts.backup_db as backup_mod
from scripts.backup_db import backup_database


@pytest.fixture
def sqlite_db(tmp_path, monkeypatch):
    """Временная SQLite-БД с данными + конфиг бэкапа в tmp_path."""
    db_file = tmp_path / "sales_agent.db"
    conn = sqlite3.connect(str(db_file))
    conn.execute("CREATE TABLE leads (id INTEGER PRIMARY KEY, name TEXT)")
    conn.execute("INSERT INTO leads (name) VALUES ('Backup Co')")
    conn.commit()
    conn.close()

    backup_dir = tmp_path / "backups"
    monkeypatch.setattr(backup_mod.settings, "db_url", f"sqlite+aiosqlite:///{db_file.as_posix()}")
    monkeypatch.setattr(backup_mod.settings, "backup_dir", str(backup_dir))
    monkeypatch.setattr(backup_mod.settings, "backup_keep", 3)
    return db_file, backup_dir


def test_sqlite_backup_creates_consistent_copy(sqlite_db):
    db_file, backup_dir = sqlite_db
    result = backup_database()

    assert result is not None and result.exists()
    # Копия содержит те же данные (backup API, не побайтовый copy)
    conn = sqlite3.connect(str(result))
    rows = conn.execute("SELECT name FROM leads").fetchall()
    conn.close()
    assert rows == [("Backup Co",)]


def test_sqlite_backup_rotation(sqlite_db):
    _db_file, backup_dir = sqlite_db
    for _ in range(5):
        backup_database()

    backups = list(backup_dir.glob("sales_agent_*.db"))
    assert len(backups) == 3  # backup_keep=3


def test_missing_db_file_returns_none(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(backup_mod.settings, "db_url", "sqlite+aiosqlite:///nonexistent.db")
    monkeypatch.setattr(backup_mod.settings, "backup_dir", str(tmp_path / "backups"))

    assert backup_database() is None
    assert "not found" in capsys.readouterr().out.lower()


def test_unsupported_driver_returns_none(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(backup_mod.settings, "db_url", "mysql+pymysql://u:p@h/db")
    monkeypatch.setattr(backup_mod.settings, "backup_dir", str(tmp_path / "backups"))

    assert backup_database() is None
    assert "Unsupported" in capsys.readouterr().out


def test_postgres_without_pg_dump_returns_none(tmp_path, monkeypatch, capsys):
    """PG-бэкап без pg_dump в PATH — понятное сообщение, без падения."""
    monkeypatch.setattr(
        backup_mod.settings, "db_url", "postgresql+asyncpg://u:p@localhost:5432/db"
    )
    monkeypatch.setattr(backup_mod.settings, "backup_dir", str(tmp_path / "backups"))
    monkeypatch.setattr(backup_mod.shutil, "which", lambda _cmd: None)

    assert backup_database() is None
    assert "pg_dump not found" in capsys.readouterr().out
