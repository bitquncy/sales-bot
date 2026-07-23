"""Rate limiting middleware: Redis-backed in production, local fallback in dev.

Ограничивает количество сообщений/callback-запросов от одного пользователя
в единицу времени. Предотвращает:
- DoS-атаки через флуд сообщений
- Перерасход LLM-лимита через спам кнопок "Анализ"
- Утилизацию ресурсов при массовых запросах к Overpass API

Реализация через in-memory хранилище (для production — Redis).
"""

import time
import asyncio
from collections import defaultdict
from typing import Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject

from config import settings
from utils.emoji_config import P
from utils import redis_client

# Лимиты (в секундах). Type-specific лимиты оставлены как дополнительный слой,
# но главная защита — общий user bucket ниже (закрывает обход message+callback).
MESSAGE_RATE_LIMIT = 1  # Не более 1 сообщения в секунду
CALLBACK_RATE_LIMIT = 0.5  # Не более 2 callback в секунду

RATE_LIMIT_TEXT = f"{P.TIMER} Слишком быстро. Подожди немного."


class RateLimitMiddleware(BaseMiddleware):
    """Middleware: ограничивает частоту запросов от пользователя.
    
    Хранит timestamp последнего запроса для каждого пользователя.
    Если между запросами прошло меньше лимита — блокирует с предупреждением.
    
    NOTE: In-memory хранилище НЕ подходит для horizontal scaling.
    Для production используйте Redis с TTL ключами.
    """

    def __init__(self):
        super().__init__()
        # {user_id: {'global': timestamp, 'message': timestamp, 'callback': timestamp}}
        self._last_request: dict[int, dict[str, float]] = defaultdict(dict)
        self._memory_lock = asyncio.Lock()

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict], Awaitable],
        event: TelegramObject,
        data: dict,
    ):
        user = data.get("event_from_user")
        if user is None:
            # Событие без пользователя (channel post и т.п.) — пропускаем
            return await handler(event, data)

        user_id = user.id
        # Wall-clock is retained for compatibility with existing middleware
        # tests/configuration; the per-instance asyncio lock makes the claim
        # atomic. Redis uses TTL and is not affected by clock rollback.
        current_time = time.time()

        # Определяем тип события и соответствующий лимит
        if isinstance(event, Message):
            event_type = "message"
            rate_limit = MESSAGE_RATE_LIMIT
        elif isinstance(event, CallbackQuery):
            event_type = "callback"
            rate_limit = CALLBACK_RATE_LIMIT
        else:
            # Неизвестный тип — пропускаем без ограничений
            return await handler(event, data)

        # SEC-FIX: общий bucket на ВСЕ типы апдейтов. Без него можно было
        # чередовать message/callback и получать эффективный лимит выше.
        global_limit = max(0.0, settings.user_global_rate_limit_seconds)
        if global_limit and not await self._claim_global_slot(user_id, current_time, global_limit):
            await self._notify_limited(event)
            return None

        if not await self._claim_type_slot(user_id, event_type, current_time, rate_limit):
            # Слишком быстро — блокируем
            await self._notify_limited(event)
            return None

        # Очистка старых записей (memory leak prevention)
        # Удаляем записи старше 1 часа
        if len(self._last_request) > 1000:  # Защита от переполнения
            cutoff = current_time - 3600
            self._last_request = defaultdict(
                dict,
                {
                    uid: timestamps
                    for uid, timestamps in self._last_request.items()
                    if any(ts > cutoff for ts in timestamps.values())
                },
            )

        return await handler(event, data)

    async def _claim_global_slot(self, user_id: int, now: float, interval: float) -> bool:
        redis = await redis_client.get_redis()
        if redis:
            try:
                ttl_ms = max(1, int(interval * 1000))
                return bool(await redis.set(
                    f"rate:user:{user_id}:global", "1", nx=True, px=ttl_ms
                ))
            except Exception:
                # Production config requires Redis availability at startup; an
                # operational failure degrades to process-local protection.
                pass
        async with self._memory_lock:
            last = self._last_request[user_id].get("global", 0)
            if now - last < interval:
                return False
            self._last_request[user_id]["global"] = now
            return True

    async def _claim_type_slot(
        self, user_id: int, event_type: str, now: float, interval: float
    ) -> bool:
        async with self._memory_lock:
            last = self._last_request[user_id].get(event_type, 0)
            if now - last < interval:
                return False
            self._last_request[user_id][event_type] = now
            return True

    async def _notify_limited(self, event: TelegramObject) -> None:
        if isinstance(event, CallbackQuery):
            try:
                await event.answer(RATE_LIMIT_TEXT, show_alert=True)
            except Exception:
                pass
        elif isinstance(event, Message):
            try:
                await event.answer(RATE_LIMIT_TEXT)
            except Exception:
                pass
