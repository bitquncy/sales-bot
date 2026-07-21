"""Кэш результатов AI-анализа (PERF-2).

Использует Redis при наличии (персистентность + multi-instance), иначе in-memory
с TTL. Кэшируется analyze_company: (name, address, phone, website) -> (score,
analysis, has_online_booking). Ключ — SHA256 от нормализованных входных данных.

Попадание в кэш экономит токены LLM и не тратит дневной бюджет вызовов
(repo.check_llm_budget проверяется ДО кэша в handlers/analysis).
"""

import hashlib
import json
import logging
import time

from utils import redis_client

logger = logging.getLogger(__name__)

# TTL кэша (24 часа). Redis TTL задаётся при SET; memory — проверяем при GET.
CACHE_TTL_SECONDS = 24 * 3600

# In-memory fallback: {key: (expires_at, json_value)}
_memory_cache: dict[str, tuple[float, str]] = {}


def _normalize_company_info(name: str, address: str | None, phone: str | None, website: str | None) -> dict:
    """Нормализует данные компании для стабильного кэш-ключа.
    
    Убирает регистр/пробелы, сортирует поля — одна и та же компания даёт
    один хэш независимо от порядка аргументов или капитализации.
    """
    return {
        "name": (name or "").strip().lower(),
        "address": (address or "").strip().lower(),
        "phone": (phone or "").strip(),
        "website": (website or "").strip().lower(),
    }


def make_cache_key(name: str, address: str | None, phone: str | None, website: str | None) -> str:
    """Генерирует кэш-ключ для analyze_company."""
    normalized = _normalize_company_info(name, address, phone, website)
    payload = json.dumps(normalized, ensure_ascii=False, sort_keys=True)
    key_hash = hashlib.sha256(payload.encode()).hexdigest()[:16]
    return f"llm_analysis:{key_hash}"


async def get_cached_analysis(key: str) -> tuple[int, str, bool | None] | None:
    """Возвращает закэшированный результат анализа или None при промахе."""
    # Попытка Redis
    redis = await redis_client.get_redis()
    if redis:
        try:
            cached = await redis.get(key)
            if cached:
                data = json.loads(cached)
                return data["score"], data["analysis"], data.get("has_online_booking")
        except Exception as exc:
            logger.debug("Redis cache GET failed for %s: %s", key, exc)
    
    # Fallback: memory cache
    now = time.time()
    if key in _memory_cache:
        expires_at, cached_json = _memory_cache[key]
        if now < expires_at:
            data = json.loads(cached_json)
            return data["score"], data["analysis"], data.get("has_online_booking")
        # Истёк TTL — удаляем
        del _memory_cache[key]
    
    return None


async def set_cached_analysis(
    key: str,
    score: int,
    analysis: str,
    has_online_booking: bool | None,
) -> None:
    """Сохраняет результат анализа в кэш с TTL."""
    data = {
        "score": score,
        "analysis": analysis,
        "has_online_booking": has_online_booking,
    }
    cached_json = json.dumps(data, ensure_ascii=False)
    
    # Попытка Redis
    redis = await redis_client.get_redis()
    if redis:
        try:
            await redis.setex(key, CACHE_TTL_SECONDS, cached_json)
            return
        except Exception as exc:
            logger.debug("Redis cache SET failed for %s: %s", key, exc)
    
    # Fallback: memory cache
    expires_at = time.time() + CACHE_TTL_SECONDS
    _memory_cache[key] = (expires_at, cached_json)
    
    # Простая очистка устаревших записей (защита от бесконечного роста)
    if len(_memory_cache) > 1000:
        now = time.time()
        expired = [k for k, (exp, _) in _memory_cache.items() if exp < now]
        for k in expired:
            del _memory_cache[k]


def reset_cache() -> None:
    """Очищает memory cache (для тестов)."""
    _memory_cache.clear()
