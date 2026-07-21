"""Тесты точки входа: чистая остановка по Ctrl+C и корректный код выхода.

asyncio.run замокан — реальный polling не стартует, проверяем только обёртку
run() над ним.
"""

import pytest

import bot


@pytest.mark.asyncio
async def test_optional_background_task_does_not_crash_bot(monkeypatch):
    class FakeBotSession:
        async def close(self):
            return None

    class FakeBot:
        def __init__(self, *args, **kwargs):
            self.session = FakeBotSession()

    class FakeStorage:
        async def close(self):
            return None

    class FakeDispatcher:
        def __init__(self, storage=None):
            self.storage = storage
            self.message = type("M", (), {"outer_middleware": lambda *a, **k: None, "middleware": lambda *a, **k: None})()
            self.callback_query = type("C", (), {"outer_middleware": lambda *a, **k: None, "middleware": lambda *a, **k: None})()

        def include_routers(self, *args, **kwargs):
            return None

        async def start_polling(self, _bot):
            await asyncio.sleep(0.05)

    import asyncio

    async def fake_init_db():
        return None

    async def fake_reminders_loop(*args, **kwargs):
        await asyncio.sleep(10)

    async def fake_retention_loop(*args, **kwargs):
        await asyncio.sleep(10)

    async def fake_chat_monitor(*args, **kwargs):
        raise RuntimeError("chat monitor init failed")

    monkeypatch.setattr(bot, "Bot", FakeBot)
    monkeypatch.setattr(bot, "Dispatcher", FakeDispatcher)
    monkeypatch.setattr(bot, "MemoryStorage", FakeStorage)
    monkeypatch.setattr(bot, "init_db", fake_init_db)
    monkeypatch.setattr(bot, "restrict_file_permissions", lambda *_a, **_k: None)
    monkeypatch.setattr(bot, "restrict_sqlite_permissions", lambda *_a, **_k: None)
    monkeypatch.setattr(bot, "validate_config", lambda _settings: [])
    monkeypatch.setattr(bot, "init_sentry", lambda: None)
    monkeypatch.setattr(bot, "reminders_loop", fake_reminders_loop)
    monkeypatch.setattr(bot, "retention_loop", fake_retention_loop)
    monkeypatch.setattr(bot.settings, "redis_url", "")
    monkeypatch.setattr(bot.settings, "auto_create_schema", True)
    monkeypatch.setattr(bot.settings, "bot_token", "123:abc")
    monkeypatch.setattr(bot.settings, "chat_monitor_owner_tg_id", 1)
    monkeypatch.setattr(bot.settings, "chat_monitor_api_id", 1)
    monkeypatch.setattr(bot.settings, "chat_monitor_api_hash", "hash")
    monkeypatch.setattr(bot.settings, "chat_monitor_phone", "+70000000000")
    monkeypatch.setattr(bot.settings, "chat_monitor_session_path", "chat_monitor.session")
    monkeypatch.setattr(bot.settings, "chat_monitor_chats", "@testchat")

    import chat_monitor.runner as runner
    monkeypatch.setattr(runner, "run_chat_monitor", fake_chat_monitor)

    await bot.main()


def test_ensure_session_path_ready_creates_parent(tmp_path, monkeypatch):
    from chat_monitor import runner

    target = tmp_path / "nested" / "chat_monitor.session"
    monkeypatch.setattr(runner.settings, "chat_monitor_session_path", str(target))
    runner.ensure_session_path_ready()
    assert target.parent.exists()


def _closing_run(exc):
    """Фейковый asyncio.run: закрывает корутину (без warning) и бросает exc."""
    def _fake(coro):
        coro.close()
        raise exc
    return _fake


def test_run_clean_shutdown_on_ctrl_c(monkeypatch, caplog):
    # Ctrl+C -> KeyboardInterrupt сквозь asyncio.run. run() должен проглотить его,
    # залогировать короткое сообщение и вернуться штатно (без traceback наружу).
    monkeypatch.setattr(bot.asyncio, "run", _closing_run(KeyboardInterrupt()))
    with caplog.at_level("INFO"):
        bot.run()  # не должно бросить
    assert any("Ctrl+C" in r.message for r in caplog.records)


def test_run_propagates_nonzero_systemexit(monkeypatch):
    # sys.exit(1) из main() (напр. нет BOT_TOKEN) -> SystemExit(1). run() НЕ
    # перехватывает его: ненулевой код выхода сохраняется (это ошибка запуска).
    monkeypatch.setattr(bot.asyncio, "run", _closing_run(SystemExit(1)))
    with pytest.raises(SystemExit) as exc_info:
        bot.run()
    assert exc_info.value.code == 1
