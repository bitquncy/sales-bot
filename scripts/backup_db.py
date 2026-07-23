"""P-7: Автобэкап БД с ротацией копий (SQLite и PostgreSQL).

Запуск:
    python -m scripts.backup_db
    или: python scripts/backup_db.py

Через cron (Linux/Mac):
    0 3 * * * cd /path/to/project && venv/bin/python -m scripts.backup_db

Через Task Scheduler (Windows) или run.bat:
    venv\\Scripts\\python -m scripts.backup_db

Ротация: остаётся последние backup_keep копий (по умолчанию 14).

SQLite: используется sqlite3 backup API (WAL-safe) — копия консистентна
даже пока бот пишет в БД. shutil.copy2 файла в WAL-режиме НЕбезопасен:
можно скопировать файл посреди транзакции.

PostgreSQL: вызывается pg_dump (должен быть установлен на машине —
входит в поставку PostgreSQL). Пароль передаётся через PGPASSWORD,
не светится в командной строке.
"""

import os
import shutil
import sqlite3
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

# Позволяем запуск из корня проекта
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy.engine.url import make_url

from config import settings
from utils.backup_crypto import encrypt_backup_file


def _timestamp() -> str:
    # Микросекунды: два запуска в одну секунду не должны перезаписывать
    # друг друга (иначе ротация теряет копии).
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f")


def _rotate(backup_dir: Path, pattern: str) -> None:
    """Удаляет старые копии, оставляя backup_keep последних по mtime."""
    backups = sorted(
        backup_dir.glob(pattern),
        key=lambda f: f.stat().st_mtime,
        reverse=True,
    )
    for old_file in backups[settings.backup_keep:]:
        old_file.unlink()
        print(f"Old backup removed: {old_file}")


def _backup_sqlite(db_path: Path, backup_dir: Path) -> Path | None:
    """WAL-safe бэкап SQLite через sqlite3 backup API."""
    if not db_path.exists():
        print(f"DB file not found: {db_path}")
        return None

    backup_file = backup_dir / f"sales_agent_{_timestamp()}.db"

    # backup API копирует постранично с учётом WAL — консистентный снапшот
    # без блокировки писателей (в отличие от shutil.copy2 файла БД).
    source = sqlite3.connect(str(db_path))
    try:
        dest = sqlite3.connect(str(backup_file))
        try:
            source.backup(dest)
        finally:
            dest.close()
    finally:
        source.close()

    if settings.backup_encryption_key:
        backup_file = encrypt_backup_file(backup_file, settings.backup_encryption_key)
    else:
        os.chmod(backup_file, 0o600)
    print(f"Backup created: {backup_file}")
    _rotate(backup_dir, "sales_agent_*.db*")
    return backup_file


def _backup_postgres(url, backup_dir: Path) -> Path | None:
    """Бэкап PostgreSQL через pg_dump (требуется установленный клиент PG)."""
    pg_dump = shutil.which("pg_dump")
    if pg_dump is None:
        print(
            "pg_dump not found in PATH. Установите PostgreSQL client tools "
            "(https://www.postgresql.org/download/) или используйте docker: "
            "docker compose exec postgres pg_dump -U <user> <db> > backup.sql"
        )
        return None

    backup_file = backup_dir / f"sales_agent_{_timestamp()}.sql"

    env = os.environ.copy()
    if url.password:
        env["PGPASSWORD"] = url.password

    cmd = [
        pg_dump,
        "-h", url.host or "localhost",
        "-p", str(url.port or 5432),
        "-U", url.username or "postgres",
        "-d", url.database or "sales_agent",
        "-f", str(backup_file),
    ]
    try:
        subprocess.run(cmd, check=True, env=env, capture_output=True, text=True)
    except subprocess.CalledProcessError as exc:
        print(f"pg_dump failed (code {exc.returncode}): {exc.stderr.strip()}")
        if backup_file.exists():
            backup_file.unlink()  # не оставляем битый дамп
        return None

    if settings.backup_encryption_key:
        backup_file = encrypt_backup_file(backup_file, settings.backup_encryption_key)
    else:
        os.chmod(backup_file, 0o600)
    print(f"Backup created: {backup_file}")
    _rotate(backup_dir, "sales_agent_*.sql*")
    return backup_file


def backup_database() -> Path | None:
    """Создаёт бэкап БД (движок определяется из DB_URL). Возвращает путь к копии."""
    url = make_url(settings.db_url)

    backup_dir = Path(settings.backup_dir)
    backup_dir.mkdir(parents=True, exist_ok=True)
    if os.name != "nt":
        os.chmod(backup_dir, 0o700)

    if url.drivername.startswith("sqlite"):
        # Формат: sqlite+aiosqlite:///./sales_agent.db
        return _backup_sqlite(Path(url.database or ""), backup_dir)
    if url.drivername.startswith("postgresql"):
        return _backup_postgres(url, backup_dir)

    print(f"Unsupported database for backup: {url.drivername}")
    return None


if __name__ == "__main__":
    raise SystemExit(0 if backup_database() is not None else 1)
