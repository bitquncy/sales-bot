"""Тесты cooldown на автора (CHATMON-1) и интеграции в processor."""

import time

from chat_monitor import filtering
from chat_monitor.filtering import author_on_cooldown, reset_author_cooldowns


def setup_function():
    reset_author_cooldowns()


def test_first_call_not_on_cooldown():
    assert author_on_cooldown(author_id=1, cooldown_seconds=3600) is False


def test_second_call_within_cooldown():
    assert author_on_cooldown(author_id=1, cooldown_seconds=3600) is False
    assert author_on_cooldown(author_id=1, cooldown_seconds=3600) is True


def test_cooldown_expires():
    now = time.time()
    assert author_on_cooldown(author_id=1, cooldown_seconds=3600, now=now) is False
    # через 2 часа cooldown истёк
    assert author_on_cooldown(author_id=1, cooldown_seconds=3600, now=now + 7200) is False


def test_cooldown_per_author():
    assert author_on_cooldown(author_id=1, cooldown_seconds=3600) is False
    # другой автор не затронут
    assert author_on_cooldown(author_id=2, cooldown_seconds=3600) is False
    # первый всё ещё на cooldown
    assert author_on_cooldown(author_id=1, cooldown_seconds=3600) is True


def test_cooldown_disabled_with_zero():
    assert author_on_cooldown(author_id=1, cooldown_seconds=0) is False
    assert author_on_cooldown(author_id=1, cooldown_seconds=0) is False


def test_reset_clears_cooldowns():
    author_on_cooldown(author_id=1, cooldown_seconds=3600)
    reset_author_cooldowns()
    assert author_on_cooldown(author_id=1, cooldown_seconds=3600) is False


def test_dictionary_cleanup_on_overflow(monkeypatch):
    """При переполнении словарь чистится от устаревших записей."""
    now = time.time()
    # Заполняем словарь старыми записями (за пределами cooldown)
    for i in range(filtering._MAX_COOLDOWN_ENTRIES + 1):
        filtering._author_last_scored[i] = now - 7200  # 2 часа назад

    # Новый вызов триггерит очистку: старые записи удаляются
    author_on_cooldown(author_id=999_999, cooldown_seconds=3600, now=now)
    assert len(filtering._author_last_scored) <= 2  # осталась только свежая


# ---------- Интеграция в processor ----------


async def test_processor_skips_author_on_cooldown(session_factory, monkeypatch):
    """Второе сообщение того же автора не доходит до LLM-скоринга."""
    from datetime import datetime, timezone

    from chat_monitor.processor import ChatMessageCandidate, process_candidate
    from config import settings

    monkeypatch.setattr(settings, "chat_monitor_author_cooldown_seconds", 3600)
    monkeypatch.setattr(settings, "llm_daily_limit", 0)

    llm_calls = []

    async def fake_score(message_text, username=None, source_chat=None, client=None):
        llm_calls.append(message_text)
        return 0.1, "низкий скор", False  # ниже min_score — лид не создаётся

    monkeypatch.setattr("chat_monitor.processor.score_nail_chat_message", fake_score)

    candidate = ChatMessageCandidate(
        source_chat="test_chat",
        user_id=42,
        username="nail_master",
        message_text="маникюр запись свободное окошко",
        message_date=datetime.now(timezone.utc),
        message_id=1,
    )

    # Первое сообщение — доходит до LLM
    await process_candidate(candidate, session_factory, owner_tg_id=1, min_score=0.7)
    assert len(llm_calls) == 1

    # Второе сообщение того же автора — блокируется cooldown'ом, LLM не вызывается
    candidate2 = ChatMessageCandidate(
        source_chat="test_chat",
        user_id=42,
        username="nail_master",
        message_text="педикюр принимаю на дому",
        message_date=datetime.now(timezone.utc),
        message_id=2,
    )
    await process_candidate(candidate2, session_factory, owner_tg_id=1, min_score=0.7)
    assert len(llm_calls) == 1  # LLM не вызывался повторно
