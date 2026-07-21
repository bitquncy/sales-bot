"""Форсирование прав доступа к файлам с секретами/ПДн (SEC-FIX-1).

Файлы вроде Telethon-сессии (= rootkey к аккаунту) и SQLite-БД (= вся CRM)
не должны быть читаемы другими пользователями ОС. Umask по умолчанию может
оставить 0644 — форсируем 0600 при старте.

На Windows POSIX-права не применяются — os.chmod меняет только бит read-only,
поэтому вызов безопасен, но фактически no-op (защита там — ACL профиля).
"""

import logging
import os
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)

OWNER_ONLY = 0o600


def _is_windows() -> bool:
    """Проверка платформы вынесена отдельно, чтобы тесты могли мокать её,
    не трогая глобальный os.name (его мок ломает pathlib на Windows)."""
    return os.name == "nt"


def restrict_file_permissions(path: str | Path, mode: int = OWNER_ONLY) -> bool:
    """Выставляет файлу права owner-only (0600). Возвращает True при успехе.

    Не падает при отсутствии файла (сессия/БД могут ещё не существовать —
    тогда права выставятся при следующем старте после их создания).
    """
    p = Path(path)
    if not p.exists():
        logger.debug("restrict_file_permissions: %s не существует, пропуск", p)
        return False
    if _is_windows():
        username = os.environ.get("USERNAME")
        domain = os.environ.get("USERDOMAIN")
        principal = f"{domain}\\{username}" if domain and username else username
        if not principal:
            logger.warning("Cannot determine Windows user for ACL: %s", p)
            return False
        try:
            subprocess.run(
                [
                    "icacls", str(p), "/inheritance:r",
                    "/grant:r", f"{principal}:(F)",
                    "/grant:r", "*S-1-5-18:(F)",
                    "/grant:r", "*S-1-5-32-544:(F)",
                ],
                check=True,
                capture_output=True,
                text=True,
            )
            logger.info("Restricted Windows ACL: %s", p)
            return True
        except (OSError, subprocess.CalledProcessError) as exc:
            logger.warning("Failed to restrict Windows ACL for %s: %s", p, exc)
            return False
    try:
        os.chmod(p, mode)
        logger.info("Права %o выставлены: %s", mode, p)
        return True
    except OSError as exc:
        logger.warning("Не удалось выставить права %o на %s: %s", mode, p, exc)
        return False


def restrict_sqlite_permissions(db_url: str) -> None:
    """Выставляет 0600 на файл SQLite (и WAL/SHM) из DB_URL."""
    if not db_url.startswith("sqlite"):
        return
    db_path = db_url.split("///")[-1]
    if not db_path or db_path == ":memory:":
        return
    restrict_file_permissions(db_path)
    # WAL-файлы содержат те же данные, что и основная БД
    restrict_file_permissions(db_path + "-wal")
    restrict_file_permissions(db_path + "-shm")
