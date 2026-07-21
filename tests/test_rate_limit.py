"""Тесты RateLimitMiddleware: общий bucket закрывает обход message+callback."""

from types import SimpleNamespace

from tests.fakes import FakeCallback, FakeMessage
from utils.rate_limit import RateLimitMiddleware


async def test_global_bucket_blocks_alternating_message_callback(monkeypatch):
    import utils.rate_limit as rl

    monkeypatch.setattr(rl.settings, "user_global_rate_limit_seconds", 10.0)
    monkeypatch.setattr(rl, "Message", FakeMessage)
    monkeypatch.setattr(rl, "CallbackQuery", FakeCallback)
    now = [1000.0]
    monkeypatch.setattr(rl.time, "time", lambda: now[0])

    mw = RateLimitMiddleware()
    calls = []

    async def handler(event, data):
        calls.append(event)
        return "ok"

    user = SimpleNamespace(id=123)
    msg = FakeMessage(user_id=123)
    cb = FakeCallback("x", user_id=123, message=msg)

    assert await mw(handler, msg, {"event_from_user": user}) == "ok"
    assert await mw(handler, cb, {"event_from_user": user}) is None
    assert len(calls) == 1
    assert cb.alert_texts()


async def test_global_bucket_allows_after_interval(monkeypatch):
    import utils.rate_limit as rl

    monkeypatch.setattr(rl.settings, "user_global_rate_limit_seconds", 0.5)
    monkeypatch.setattr(rl, "Message", FakeMessage)
    monkeypatch.setattr(rl, "CallbackQuery", FakeCallback)
    now = [1000.0]
    monkeypatch.setattr(rl.time, "time", lambda: now[0])

    mw = RateLimitMiddleware()
    calls = []

    async def handler(event, data):
        calls.append(event)
        return "ok"

    user = SimpleNamespace(id=123)
    msg = FakeMessage(user_id=123)
    cb = FakeCallback("x", user_id=123, message=msg)

    assert await mw(handler, msg, {"event_from_user": user}) == "ok"
    now[0] += 0.6
    assert await mw(handler, cb, {"event_from_user": user}) == "ok"
    assert len(calls) == 2
