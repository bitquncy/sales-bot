"""Тесты LLM-кэша (PERF-2): ключи, TTL, memory-fallback, попадание/промах."""

import time

from services import llm_cache


def test_cache_key_stable_and_normalized():
    k1 = llm_cache.make_cache_key("Салон Красота", "ул. Ленина 1", "+77001", "https://a.kz")
    k2 = llm_cache.make_cache_key("  салон красота ", "УЛ. ЛЕНИНА 1", "+77001", "HTTPS://A.KZ")
    # регистр и пробелы не влияют на ключ
    assert k1 == k2


def test_cache_key_differs_for_different_companies():
    k1 = llm_cache.make_cache_key("A", None, None, None)
    k2 = llm_cache.make_cache_key("B", None, None, None)
    assert k1 != k2


async def test_cache_set_and_get():
    key = llm_cache.make_cache_key("Тест", None, None, None)
    await llm_cache.set_cached_analysis(key, 88, "анализ", False)

    result = await llm_cache.get_cached_analysis(key)
    assert result == (88, "анализ", False)


async def test_cache_miss_returns_none():
    result = await llm_cache.get_cached_analysis("llm_analysis:nonexistent")
    assert result is None


async def test_cache_stores_none_booking():
    key = llm_cache.make_cache_key("NoBooking", None, None, None)
    await llm_cache.set_cached_analysis(key, 50, "x", None)
    score, analysis, booking = await llm_cache.get_cached_analysis(key)
    assert score == 50 and booking is None


async def test_cache_expires(monkeypatch):
    key = llm_cache.make_cache_key("TTL Co", None, None, None)
    await llm_cache.set_cached_analysis(key, 10, "old", True)

    # Перематываем время за пределы TTL — запись должна считаться просроченной
    future = time.time() + llm_cache.CACHE_TTL_SECONDS + 1
    monkeypatch.setattr(time, "time", lambda: future)

    assert await llm_cache.get_cached_analysis(key) is None
