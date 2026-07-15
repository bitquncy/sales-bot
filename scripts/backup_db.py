"""P-7: Автобэкап sales_agent.db с ротацией копий.

Запуск:
    python -m scripts.backup_db
    или: python scripts/backup_db.py

Через cron (Linux/Mac):
    0 3 * * * cd /path/to/project && venv/bin/python -m scripts.backup_db

Через Task Scheduler (Windows) или run.bat:
    venv\\Scripts\\python -m scripts.backup_db

Ротация: остаётся последние backup_keep копий (по умолчанию 14).
"""

import os
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

# Позволяем запуск из корня проекта
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import settings


def backup_database() -> Path | None:
    """Копирует БД в backup_dir с timestamp-именем. Возвращает путь к копии."""
    # Извлекаем путь к файлу БД из db_url
    # Формат: sqlite+aiosqlite:///./sales_agent.db
    db_path_str = settings.db_url.split("///")[-1]
    db_path = Path(db_path_str)

    if not db_path.exists():
        print(f"DB file not found: {db_path}")
        return None

    backup_dir = Path(settings.backup_dir)
    backup_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    backup_file = backup_dir / f"sales_agent_{timestamp}.db"

    shutil.copy2(db_path, backup_file)
    print(f"Backup created: {backup_file}")

    # Ротация: удаляем старые копии, оставляем backup_keep последних
    backups = sorted(
        backup_dir.glob("sales_agent_*.db"),
        key=lambda f: f.stat().st_mtime,
        reverse=True,
    )
    for old_file in backups[settings.backup_keep:]:
        old_file.unlink()
        print(f"Old backup removed: {old_file}")

    return backup_file


if __name__ == "__main__":
    backup_database()
