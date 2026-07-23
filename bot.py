"""Точка входа: polling + фоновый поллер напоминаний."""

import asyncio
import logging
import sys

from aiohttp import web
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.fsm.storage.redis import RedisStorage
from redis.asyncio import Redis

from config import settings
from db.base import init_db, session_factory, verify_schema
from handlers import analysis, chat_monitor, common, crm, menu, messages, search, start
from services.reminders import reminders_loop
from services.retention import retention_loop
from utils.access import AllowlistMiddleware
from utils.config_validator import validate_config
from utils.error_handler import ErrorHandlerMiddleware
from utils.file_perms import restrict_file_permissions, restrict_sqlite_permissions
from utils.rate_limit import RateLimitMiddleware
from utils.sentry import SentryContextMiddleware, init_sentry
from utils.sentry import capture_exception

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


async def _start_health_server() -> tuple[web.AppRunner, web.BaseSite] | None:
    if settings.port <= 0:
        return None

    async def health(_request: web.Request) -> web.Response:
        return web.json_response({"ok": True})

    app = web.Application()
    app.router.add_get("/", health)
    app.router.add_get("/healthz", health)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, host="0.0.0.0", port=settings.port)
    await site.start()
    logger.info("Health server listening on port %s", settings.port)
    return runner, site


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

    # MONITORING-2: Sentry инициализируется до старта — ловит ошибки инициализации БД
    init_sentry()

    # .env contains bot/LLM/encryption credentials.
    restrict_file_permissions(".env")

    if settings.auto_create_schema:
        await init_db()
    else:
        await verify_schema()
    # SEC-FIX-1: файл SQLite (вся CRM + ПДн) — только владельцу ОС
    restrict_sqlite_permissions(settings.db_url)

    bot = Bot(token=settings.bot_token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    
    # SECURITY-6: Конфигурация FSM storage - используем Redis если доступен
    storage = None
    if settings.redis_url:
        try:
            redis = Redis.from_url(settings.redis_url, decode_responses=True)
            await redis.ping()
            storage = RedisStorage(redis)
            logger.info("FSM storage: Redis (persistent)")
        except Exception as exc:
            if settings.environment.lower() == "production":
                raise RuntimeError("Redis is required and unavailable in production") from exc
            logger.warning("Redis недоступен (%s), используем MemoryStorage", exc)
            storage = MemoryStorage()
    else:
        storage = MemoryStorage()
        logger.info("FSM storage: Memory (потеря состояний при рестарте)")
    
    dp = Dispatcher(storage=storage)

    # SECURITY-1: Rate limiting — защита от флуда и DoS
    rate_limit_mw = RateLimitMiddleware()
    dp.message.outer_middleware(rate_limit_mw)
    dp.callback_query.outer_middleware(rate_limit_mw)

    # P-1: allowlist после rate limit — flood запрещённого пользователя не
    # должен генерировать ответ Telegram на каждый update.
    allowlist_mw = AllowlistMiddleware()
    dp.message.outer_middleware(allowlist_mw)
    dp.callback_query.outer_middleware(allowlist_mw)
    
    # ERROR-1: Глобальная обработка ошибок
    error_handler_mw = ErrorHandlerMiddleware()
    dp.message.middleware(error_handler_mw)
    dp.callback_query.middleware(error_handler_mw)

    # MONITORING-2: Контекст пользователя/FSM для событий Sentry (inner middleware,
    # после error_handler — scope активен на момент перехвата исключения)
    sentry_mw = SentryContextMiddleware()
    dp.message.middleware(sentry_mw)
    dp.callback_query.middleware(sentry_mw)

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

    health_server = await _start_health_server()

    # Запуск фоновых задач
    background_tasks: list[tuple[str, asyncio.Task, bool]] = []
    
    # Фоновый поллер напоминаний (всегда активен)
    reminders_task = asyncio.create_task(
        reminders_loop(bot, session_factory, settings.reminders_poll_interval)
    )
    background_tasks.append(("reminders", reminders_task, True))

    # SEC-FIX-4: фоновая очистка устаревших ПДн и журналов (retention)
    retention_task = asyncio.create_task(
        retention_loop(session_factory, settings.retention_cleanup_interval_seconds)
    )
    background_tasks.append(("retention", retention_task, True))
    
    # Chat Monitor (опционально, если настроен в .env)
    if settings.chat_monitor_ready:
        logger.info("Chat Monitor: starting (config ready)")
        try:
            # Динамический импорт чтобы не блокировать если Telethon не установлен
            from chat_monitor.runner import run_chat_monitor
            
            chat_monitor_task = asyncio.create_task(
                run_chat_monitor(bot, session_factory)
            )
            background_tasks.append(("chat_monitor", chat_monitor_task, False))
            logger.info("Chat Monitor: started successfully")
        except ImportError as exc:
            logger.warning("Chat Monitor: Telethon not installed (%s), skipping", exc)
        except Exception as exc:
            logger.error("Chat Monitor: failed to start (%s), continuing without it", exc)
    else:
        logger.info("Chat Monitor: not configured (set CHAT_MONITOR_* in .env to enable)")
    
    logger.info("Bot started (polling)")
    logger.info("Background tasks: %s", ", ".join(name for name, _, _ in background_tasks))
    
    polling_task = asyncio.create_task(dp.start_polling(bot), name="telegram-polling")
    watched_tasks = [task for _, task, _ in background_tasks]
    try:
        task_meta = {task: (name, critical) for name, task, critical in background_tasks}
        while True:
            done, _pending = await asyncio.wait(
                [polling_task, *watched_tasks],
                return_when=asyncio.FIRST_COMPLETED,
            )
            if polling_task in done:
                await polling_task
                break
            for failed in done:
                name, critical = task_meta[failed]
                if failed.cancelled():
                    if critical:
                        raise RuntimeError(f"Critical background task stopped unexpectedly: {name}")
                    logger.warning("Optional background task stopped: %s", name)
                    watched_tasks = [task for task in watched_tasks if task is not failed]
                    continue
                exc = failed.exception()
                if exc is None:
                    exc = RuntimeError(f"Background task exited unexpectedly: {name}")
                capture_exception(exc)
                if critical:
                    raise exc
                logger.error("Optional background task failed (%s): %s", name, exc)
                watched_tasks = [task for task in watched_tasks if task is not failed]
            if not watched_tasks:
                await polling_task
                break
    finally:
        logger.info("Shutting down bot...")
        if not polling_task.done():
            polling_task.cancel()
        
        # Graceful shutdown: отменяем все фоновые задачи и ждем их завершения
        for name, task, _critical in background_tasks:
            logger.info("Stopping %s...", name)
            task.cancel()
            try:
                await asyncio.wait_for(task, timeout=5.0)
            except (asyncio.CancelledError, asyncio.TimeoutError):
                logger.info("%s stopped", name)
            except Exception as exc:
                logger.error("%s shutdown error: %s", name, exc)
        
        await bot.session.close()

        if health_server is not None:
            runner, _site = health_server
            await runner.cleanup()
         
        if storage and hasattr(storage, 'close'):
            logger.info("Closing FSM storage...")
            await storage.close()
        
        logger.info("Bot shutdown complete")


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
