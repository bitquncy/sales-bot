"""Тесты семафора параллелизма LLM-вызовов (PERF-3)."""

import asyncio

from services import ai
from services.ai import LLMClient


class _SlowClient(LLMClient):
    """Клиент с замедленным _complete для проверки параллелизма."""

    def __init__(self):
        self.active = 0
        self.max_active = 0

    async def _complete(self, prompt: str) -> str:
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        await asyncio.sleep(0.01)
        self.active -= 1
        return '{"score": 50, "weaknesses": [], "offer": "x", "has_online_booking": null}'


async def test_semaphore_limits_concurrency(monkeypatch):
    monkeypatch.setattr(ai.settings, "llm_max_concurrency", 2)
    # Сбрасываем кэшированный семафор, чтобы подхватился новый лимит
    monkeypatch.setattr(ai, "_llm_semaphore", None)
    monkeypatch.setattr(ai, "_llm_semaphore_loop", None)

    client = _SlowClient()
    await asyncio.gather(*[client.analyze_company(f"Co{i}") for i in range(6)])

    assert client.max_active <= 2


async def test_semaphore_recreated_per_loop(monkeypatch):
    """Семафор не ломается при смене event loop (pytest-asyncio создаёт новый на тест)."""
    monkeypatch.setattr(ai.settings, "llm_max_concurrency", 3)
    monkeypatch.setattr(ai, "_llm_semaphore", None)
    monkeypatch.setattr(ai, "_llm_semaphore_loop", None)

    s1 = ai._get_llm_semaphore()
    s2 = ai._get_llm_semaphore()
    # В рамках одного loop — тот же объект
    assert s1 is s2
