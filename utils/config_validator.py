"""Валидация конфигурации перед стартом бота (CONFIG-2).

Возвращает список строк с ошибками. Пустой список = конфиг валиден.
Предупреждения логируются, но не блокируют старт.
"""

import logging
from pathlib import Path

logger = logging.getLogger(__name__)


def validate_config(settings) -> list[str]:
    """Проверяет критичные параметры конфига. Возвращает список ошибок (блокируют старт).

    Предупреждения (не блокируют) логируются напрямую.
    """
    errors: list[str] = []

    # --- Обязательные параметры ---
    if not settings.bot_token:
        errors.append(
            "BOT_TOKEN не задан. Скопируй .env.example в .env и впиши токен от @BotFather."
        )

    # --- LLM ---
    if not settings.llm_ready:
        logger.warning(
            "Ключ LLM-провайдера (%s) не задан — AI-анализ и генерация сообщений "
            "работать не будут. Заполни LLM_API_KEY (или ANTHROPIC_API_KEY) в .env.",
            settings.llm_provider,
        )

    # --- БД ---
    db_url = settings.db_url
    if db_url.startswith("sqlite"):
        # Проверяем что директория для файла БД существует или может быть создана
        db_path_str = db_url.split("///")[-1]
        if db_path_str and db_path_str not in (":memory:", ""):
            db_dir = Path(db_path_str).parent
            if not db_dir.exists():
                try:
                    db_dir.mkdir(parents=True, exist_ok=True)
                    logger.info("Создана директория для БД: %s", db_dir)
                except OSError as exc:
                    errors.append(f"Не удалось создать директорию для БД {db_dir}: {exc}")

    # --- Бэкап ---
    backup_dir = Path(settings.backup_dir)
    if not backup_dir.exists():
        try:
            backup_dir.mkdir(parents=True, exist_ok=True)
            logger.info("Создана директория для бэкапов: %s", backup_dir)
        except OSError as exc:
            logger.warning("Не удалось создать директорию для бэкапов %s: %s", backup_dir, exc)

    # --- Allowlist ---
    if not settings.allowed_user_set:
        logger.warning(
            "ALLOWED_USER_IDS не задан — бот доступен любому пользователю Telegram. "
            "Для ограничения доступа добавь свой Telegram ID в .env: ALLOWED_USER_IDS=123456789"
        )

    # --- Проверка корректности ALLOWED_USER_IDS (нечисловые значения) ---
    if settings.allowed_user_ids.strip():
        for raw in settings.allowed_user_ids.split(","):
            value = raw.strip()
            if value and not value.lstrip("-").isdigit():
                logger.warning(
                    "ALLOWED_USER_IDS содержит нечисловое значение %r — оно будет проигнорировано.",
                    value,
                )

    # --- LLM daily limit ---
    if settings.llm_daily_limit < 0:
        errors.append(f"LLM_DAILY_LIMIT должен быть >= 0, получено: {settings.llm_daily_limit}")

    # --- Reminders poll interval ---
    if settings.reminders_poll_interval < 10:
        logger.warning(
            "REMINDERS_POLL_INTERVAL=%s слишком мал (< 10 сек) — возможна высокая нагрузка на БД.",
            settings.reminders_poll_interval,
        )

    return errors
