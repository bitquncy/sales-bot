"""Общий Redis-клиент для переиспользования (PERF-1).

Используется idempotency, LLM-кэшем и FSM storage. Lazy init + graceful fallback
при недоступности Redis — бот работает без него (с потерей персистентности).
"""

import logging
from typing import Any

from config import settings

logger = logging.getLogger(__name__)

_redis_client: Any = None  # redis.asyncio.Redis | None
_redis_available = False


async def get_redis() -> Any:  # -> redis.asyncio.Redis | None
    """Возвращает Redis-клиент (lazy init) или None при недоступности.
    
    При первом вызове пытается подключиться к Redis из REDIS_URL; если не задан
    или недоступен — возвращает None и логирует warning. Повторные вызовы
    переиспользуют результат (успешный клиент или None).
    """
    global _redis_client, _redis_available
    
    if _redis_client is not None:
        return _redis_client if _redis_available else None
    
    if not settings.redis_url:
        _redis_available = False
        logger.info("Redis: not configured (REDIS_URL empty)")
        return None
    
    try:
        from redis.asyncio import Redis
        _redis_client = Redis.from_url(settings.redis_url, decode_responses=True)
        await _redis_client.ping()
        _redis_available = True
        logger.info("Redis: connected to %s", settings.redis_url.split("@")[-1])
        return _redis_client
    except ImportError:
        logger.warning("Redis: redis-py not installed, continuing without Redis")
        _redis_available = False
        _redis_client = None
        return None
    except Exception as exc:
        logger.warning("Redis: unavailable (%s), continuing without Redis", exc)
        _redis_available = False
        _redis_client = None
        return None


def is_available() -> bool:
    """Проверяет, доступен ли Redis (после первого вызова get_redis)."""
    return _redis_available


def reset() -> None:
    """Сбрасывает состояние (для тестов)."""
    global _redis_client, _redis_available
    _redis_client = None
    _redis_available = False
