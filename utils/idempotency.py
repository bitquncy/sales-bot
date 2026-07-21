"""Идемпотентность операций с поддержкой Redis (SECURITY-7).

Предотвращает дублирование дорогостоящих операций (LLM-вызовы, внешние API)
при конкурентном доступе или повторных нажатиях кнопок.

Использует Redis если доступен (масштабируется горизонтально),
иначе fallback на in-memory (только для single-instance).
"""

import asyncio
import logging
import secrets
import time

from utils import redis_client

logger = logging.getLogger(__name__)

# Fallback: in-memory хранилище для single-instance режима
_memory_locks: dict[str, tuple[str, float]] = {}
_memory_lock = asyncio.Lock()

_RELEASE_SCRIPT = """
if redis.call('get', KEYS[1]) == ARGV[1] then
    return redis.call('del', KEYS[1])
end
return 0
"""


async def _acquire_token(key: str, ttl: int) -> str | None:
    token = secrets.token_urlsafe(24)
    redis = await redis_client.get_redis()
    if redis:
        try:
            result = await redis.set(f"lock:{key}", token, nx=True, ex=ttl)
            return token if result else None
        except Exception as exc:
            logger.error("Redis lock failed for %s: %s", key, exc)

    now = time.monotonic()
    async with _memory_lock:
        current = _memory_locks.get(key)
        if current and current[1] > now:
            return None
        _memory_locks[key] = (token, now + max(1, ttl))
        return token


async def acquire_lock(
    key: str,
    ttl: int = 60,
) -> str | None:
    """Пытается захватить блокировку для ключа.
    
    Args:
        key: Уникальный ключ операции (например, "analysis:123:456")
        ttl: Время жизни блокировки в секундах (защита от зависших операций)
    
    Returns:
        Owner token если lock захвачен, None если уже занят. Этот token нужно
        передать в release_lock — ownerless release запрещён.
    """
    return await _acquire_token(key, ttl)


async def release_lock(key: str, token: str | None = None) -> None:
    """Освобождает блокировку.
    
    Args:
        key: Уникальный ключ операции
    """
    redis = await redis_client.get_redis()
    
    if redis:
        try:
            if token is None:
                logger.warning("Refusing ownerless release of Redis lock %s", key)
                return
            await redis.eval(_RELEASE_SCRIPT, 1, f"lock:{key}", token)
            return
        except Exception as exc:
            logger.error("Redis unlock failed for %s: %s", key, exc)
    
    # Memory fallback
    async with _memory_lock:
        current = _memory_locks.get(key)
        if current and (token is None or current[0] == token):
            _memory_locks.pop(key, None)


class IdempotencyLock:
    """Context manager для идемпотентной операции.
    
    Usage:
        async with IdempotencyLock("analysis", user_id, lead_id) as acquired:
            if not acquired:
                return "Operation already in progress"
            # Выполняем операцию
            result = await expensive_operation()
            return result
    """
    
    def __init__(self, operation: str, *args, ttl: int = 60):
        """
        Args:
            operation: Тип операции (analysis, generation, export, etc.)
            *args: Параметры для формирования уникального ключа
            ttl: TTL блокировки в секундах
        """
        self.key = f"{operation}:{':'.join(map(str, args))}"
        self.ttl = ttl
        self.acquired = False
        self._token: str | None = None
    
    async def __aenter__(self) -> bool:
        self._token = await _acquire_token(self.key, self.ttl)
        self.acquired = self._token is not None
        return self.acquired
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.acquired:
            await release_lock(self.key, self._token)
        return False
