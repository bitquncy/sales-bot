"""Интеграция Sentry для мониторинга ошибок (MONITORING-2).

Активируется только при заданном SENTRY_DSN — без него бот работает как раньше,
а все функции-мосты (capture_exception и др.) становятся безопасными no-op.

Что даёт:
- необработанные исключения в хендлерах уходят в Sentry (ErrorHandlerMiddleware);
- сбои фоновых циклов (напоминания, chat_monitor) — тоже;
- контекст пользователя (tg_id, username) и FSM-состояния прикрепляется
  к событию (SentryContextMiddleware);
- ERROR+ логи автоматически собираются как события (LoggingIntegration).

PII: send_default_pii=False — IP/куки/headers не отправляем. Telegram user_id
и username прикрепляем осознанно: без них расследование инцидентов бесполезно.
"""

import json
import hashlib
import logging
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject

from config import settings

logger = logging.getLogger(__name__)

_sentry_enabled = False

# Маркер замены секретов
_REDACTED = "***REDACTED***"


def _secret_values() -> list[str]:
    """Собирает непустые секреты из конфига для вычистки из событий."""
    candidates = [
        settings.bot_token,
        settings.llm_api_key,
        settings.anthropic_api_key,
        settings.chat_monitor_api_hash,
        settings.chat_monitor_phone,
        settings.pii_encryption_key,
        settings.db_url,
        settings.redis_url,
        settings.sentry_dsn,
    ]
    # Игнорируем слишком короткие — ложные срабатывания на общих подстроках
    return [s for s in candidates if s and len(str(s)) >= 6]


def _scrub_secrets(event: dict, _hint) -> dict:
    """before_send-фильтр: заменяет значения секретов на ***REDACTED***.

    Событие сериализуется в JSON, заменяются все вхождения секретов (включая
    traceback locals, сообщения об ошибках, breadcrumbs), затем обратно.
    Это дешевле и надёжнее рекурсивного обхода структуры события.
    """
    secrets = _secret_values()
    if not secrets:
        return event
    try:
        raw = json.dumps(event, ensure_ascii=False, default=str)
        for secret in secrets:
            raw = raw.replace(str(secret), _REDACTED)
        return json.loads(raw)
    except Exception:
        # Fail closed: событие без гарантированной очистки не отправляем.
        logger.debug("Sentry scrub failed", exc_info=True)
        return None


def _scrub_breadcrumb(crumb: dict, _hint) -> dict | None:
    scrubbed = _scrub_secrets({"crumb": crumb}, None)
    return scrubbed.get("crumb") if scrubbed else None


def _hash_user_id(user_id: int) -> str:
    salt = settings.sentry_user_hash_salt or settings.pii_encryption_key
    payload = f"{salt}:{user_id}".encode()
    return hashlib.sha256(payload).hexdigest()[:20]


def init_sentry() -> bool:
    """Инициализирует Sentry SDK, если задан SENTRY_DSN. Возвращает успех."""
    global _sentry_enabled
    if not settings.sentry_dsn:
        logger.info("Sentry: disabled (SENTRY_DSN not set)")
        return False
    try:
        import sentry_sdk
        from sentry_sdk.integrations.logging import LoggingIntegration
    except ImportError:
        logger.warning("Sentry: SENTRY_DSN set but sentry-sdk is not installed")
        return False

    sentry_sdk.init(
        dsn=settings.sentry_dsn,
        environment=settings.sentry_environment,
        traces_sample_rate=settings.sentry_traces_sample_rate,
        integrations=[
            # Логи уровня INFO+ как breadcrumbs, ERROR+ — как события Sentry.
            LoggingIntegration(level=logging.INFO, event_level=logging.ERROR),
        ],
        send_default_pii=False,
        # SEC-FIX-2: вычистка секретов из событий перед отправкой
        before_send=_scrub_secrets,
        before_breadcrumb=_scrub_breadcrumb,
    )
    _sentry_enabled = True
    logger.info("Sentry: enabled (environment=%s)", settings.sentry_environment)
    return True


def is_enabled() -> bool:
    """Инициализирован ли Sentry (после вызова init_sentry)."""
    return _sentry_enabled


def capture_exception(exc: BaseException) -> None:
    """Отправляет исключение в Sentry. Безопасный no-op при выключенном Sentry."""
    if not _sentry_enabled:
        return
    try:
        import sentry_sdk

        sentry_sdk.capture_exception(exc)
    except Exception:
        # Сбой самого репортинга не должен ронять бота
        logger.debug("Sentry capture_exception failed", exc_info=True)


class SentryContextMiddleware(BaseMiddleware):
    """Прикрепляет контекст пользователя и FSM к событиям Sentry.

    Middleware — inner (регистрировать ПОСЛЕ error_handler, чтобы scope
    был активен на момент перехвата исключения).
    """

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        if not _sentry_enabled:
            return await handler(event, data)

        import sentry_sdk

        # isolation_scope — актуальный API sentry-sdk 2.x (push_scope deprecated):
        # события внутри блока видят этот scope, наружу он не утекает.
        with sentry_sdk.isolation_scope() as scope:
            user = None
            if isinstance(event, Message):
                user = event.from_user
            elif isinstance(event, CallbackQuery):
                user = event.from_user
            if user is not None:
                opaque_id = _hash_user_id(user.id)
                scope.set_user({"id": opaque_id})
                scope.set_tag("user_hash", opaque_id)

            state = data.get("state")
            if state is not None:
                try:
                    scope.set_extra("fsm_state", str(await state.get_state()))
                except Exception:
                    pass

            return await handler(event, data)
