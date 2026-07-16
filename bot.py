"""Точка входа: polling + фоновый поллер напоминаний."""

import asyncio
import logging
import sys

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from config import settings
from db.base import init_db, session_factory
from handlers import analysis, chat_monitor, common, crm, menu, messages, search, start
from services.reminders import reminders_loop
from utils.access import AllowlistMiddleware
from utils.config_validator import validate_config

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


def _check_runtime_env() -> None:
    """Не блокирующая проверка окружения запуска.

    Реальный краш `AsyncClient.__init__() ... 'proxies'` возник из-за запуска на
    глобальном Python 3.10 с несовпадающими версиями пакетов вместо venv на 3.11.
    Здесь только warning в лог — не мешаем старту, но подсвечиваем расхождение.
    """
    if sys.version_info < (3, 11):
        logger.warning(
            "Python %s.%s.%s < 3.11 — проект тестировался на 3.11+. "
            "Создай окружение через `py -3.11 -m venv venv` и запускай из него.",
            *sys.version_info[:3],
        )
    # В venv sys.prefix отличается от sys.base_prefix; в глобальном — совпадают.
    if sys.prefix == sys.base_prefix:
        logger.warning(
            "Похоже, бот запущен НЕ из venv (sys.prefix == sys.base_prefix): "
            "используются глобальные пакеты, версии которых могут не совпадать с "
            "requirements.txt. Активируй venv (venv\\Scripts\\activate) перед запуском."
        )


async def main() -> None:
    _check_runtime_env()
    # CONFIG-2: полная валидация конфига перед стартом
    errors = validate_config(settings)
    if errors:
        for err in errors:
            logger.error("Config error: %s", err)
        sys.exit(1)

    await init_db()

    bot = Bot(token=settings.bot_token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher()

    # P-1: Глобальный allowlist — перехватывает все сообщения/callbackи
    mw = AllowlistMiddleware()
    dp.message.outer_middleware(mw)
    dp.callback_query.outer_middleware(mw)

    dp.include_routers(
        common.commands_router,
        start.router,
        search.router,
        analysis.router,
        messages.router,
        chat_monitor.router,
        crm.router,
        menu.router,
        common.fallback_router,
    )

    reminders_task = asyncio.create_task(
        reminders_loop(bot, session_factory, settings.reminders_poll_interval)
    )
    logger.info("Bot started (polling)")
    try:
        await dp.start_polling(bot)
    finally:
        reminders_task.cancel()
        await bot.session.close()


def run() -> None:
    """Точка входа с чистой остановкой по Ctrl+C.

    Штатный `Ctrl+C` роняет KeyboardInterrupt сквозь asyncio.run -> длинный
    traceback, который выглядит как ошибка при обычной остановке. Ловим его явно
    и печатаем короткое сообщение, код выхода — 0.

    SystemExit намеренно НЕ перехватываем: его бросает main() через sys.exit(1)
    при отсутствии BOT_TOKEN (сообщение об ошибке уже в логе). Интерпретатор для
    SystemExit traceback не печатает, а ненулевой код возврата нужно сохранить —
    это ошибка запуска, а не штатная остановка.
    """
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Бот остановлен пользователем (Ctrl+C).")


if __name__ == "__main__":
    run()
