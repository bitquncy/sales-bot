"""Тесты точки входа: чистая остановка по Ctrl+C и корректный код выхода.

asyncio.run замокан — реальный polling не стартует, проверяем только обёртку
run() над ним.
"""

import pytest

import bot


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
