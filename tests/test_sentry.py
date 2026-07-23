"""Тесты Sentry-интеграции (MONITORING-2).

Проверяем graceful-поведение БЕЗ реального DSN: все мосты — безопасные no-op,
middleware прозрачно, init не падает при отсутствии конфига.
"""

import utils.sentry as sentry_mod
from utils.sentry import SentryContextMiddleware, capture_exception, init_sentry, is_enabled


def test_init_sentry_disabled_without_dsn(monkeypatch):
    monkeypatch.setattr(sentry_mod, "_sentry_enabled", False)
    monkeypatch.setattr(sentry_mod.settings, "sentry_dsn", "")
    assert init_sentry() is False
    assert is_enabled() is False


def test_init_sentry_with_dsn(monkeypatch):
    """С DSN SDK инициализируется (реально в сеть не ходит — init ленивый)."""
    monkeypatch.setattr(sentry_mod, "_sentry_enabled", False)
    monkeypatch.setattr(
        sentry_mod.settings, "sentry_dsn", "https://test@o123.ingest.sentry.io/456"
    )
    try:
        assert init_sentry() is True
        assert is_enabled() is True
    finally:
        # Откатываем глобальное состояние SDK, чтобы не влиять на другие тесты
        import sentry_sdk

        sentry_sdk.init()
        monkeypatch.setattr(sentry_mod, "_sentry_enabled", False)


def test_capture_exception_noop_when_disabled(monkeypatch):
    monkeypatch.setattr(sentry_mod, "_sentry_enabled", False)
    # Не должно падать
    capture_exception(ValueError("test"))


async def test_middleware_passthrough_when_disabled(monkeypatch):
    """Без Sentry middleware просто вызывает handler."""
    monkeypatch.setattr(sentry_mod, "_sentry_enabled", False)
    mw = SentryContextMiddleware()

    called = {}

    async def handler(event, data):
        called["hit"] = True
        return "ok"

    result = await mw(handler, event=object(), data={})
    assert result == "ok"
    assert called["hit"]


async def test_middleware_with_enabled_sentry(monkeypatch):
    """С включённым Sentry middleware тоже прозрачен для handler (scope — внутри)."""
    monkeypatch.setattr(sentry_mod, "_sentry_enabled", True)
    mw = SentryContextMiddleware()

    async def handler(event, data):
        return "done"

    # event — не Message/CallbackQuery, поэтому user не извлекается; state нет.
    result = await mw(handler, event=object(), data={})
    assert result == "done"
