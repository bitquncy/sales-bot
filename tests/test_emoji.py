"""Тесты emoji_config и safe_send (fallback на plain-эмодзи)."""

import ast
from pathlib import Path

import pytest
from aiogram.exceptions import TelegramBadRequest

from utils.emoji_config import CUSTOM_EMOJIS, E, P, check_emoji_config, emoji
from utils.safe_send import safe_answer, safe_bot_send, safe_edit, strip_custom_emojis


# ---------- Конфигурация ----------

def test_no_missing_ids():
    """В маппинге не должно быть незаполненных ID."""
    stats = check_emoji_config()
    assert stats["missing"] == 0
    assert stats["configured"] == stats["total"]
    assert all(v != "ЗАМЕНИТЕ_НА_REAL_ID" for v in CUSTOM_EMOJIS.values())


def test_no_duplicate_keys_in_source():
    """В исходнике CUSTOM_EMOJIS нет задвоенных ключей (Python тихо перезатирает)."""
    source = (Path(__file__).parent.parent / "utils" / "emoji_config.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == "CUSTOM_EMOJIS" for t in node.targets
        ):
            keys = [k.value for k in node.value.keys if isinstance(k, ast.Constant)]
            assert len(keys) == len(set(keys)), f"Дубли ключей: {[k for k in keys if keys.count(k) > 1]}"
            return
    pytest.fail("CUSTOM_EMOJIS не найден в utils/emoji_config.py")


def test_all_ids_are_numeric():
    assert all(v.isdigit() for v in CUSTOM_EMOJIS.values())


def test_emoji_renders_tg_tag():
    assert emoji("✅") == '<tg-emoji emoji-id="5260726538302660868">✅</tg-emoji>'


def test_emoji_fallback_for_unknown():
    assert emoji("🔥") == "🔥"
    assert emoji("🔥", fallback=False) == ""


def test_e_and_p_are_consistent():
    """E.* содержит tg-emoji для эмодзи из пака, P.* — только plain юникод."""
    assert E.CHECK.startswith("<tg-emoji")
    assert E.WARNING == "⚠️"  # нет в паке — plain
    for name in ("CHECK", "CROSS", "TIMER", "NOTE", "SEARCH"):
        assert "<" not in getattr(P, name)


# ---------- strip_custom_emojis ----------

def test_strip_replaces_tags_with_plain():
    text = f"{E.CHECK} Готово, {E.SEARCH} ищем дальше"
    assert strip_custom_emojis(text) == "✅ Готово, 🔎 ищем дальше"


def test_strip_leaves_other_html_intact():
    text = f"{E.NOTE} <b>Жирный &amp; текст</b>"
    assert strip_custom_emojis(text) == "📝 <b>Жирный &amp; текст</b>"


def test_strip_handles_empty():
    assert strip_custom_emojis("") == ""
    assert strip_custom_emojis(None) == ""


# ---------- safe_* fallback ----------

class _FlakyMessage:
    """Первый вызов с <tg-emoji> падает как Telegram при невалидном emoji-id."""

    def __init__(self):
        self.sent: list[str] = []

    async def _maybe_fail(self, text):
        if "<tg-emoji" in text:
            raise TelegramBadRequest(method=None, message="Bad Request: EMOJI_INVALID")
        self.sent.append(text)
        return text

    async def answer(self, text, **kwargs):
        return await self._maybe_fail(text)

    async def edit_text(self, text, **kwargs):
        return await self._maybe_fail(text)


class _FlakyBot:
    def __init__(self):
        self.sent: list[str] = []

    async def send_message(self, chat_id, text, **kwargs):
        if "<tg-emoji" in text:
            raise TelegramBadRequest(method=None, message="Bad Request: EMOJI_INVALID")
        self.sent.append(text)
        return text


@pytest.mark.asyncio
async def test_safe_answer_falls_back_to_plain():
    msg = _FlakyMessage()
    await safe_answer(msg, f"{E.CHECK} Готово")
    assert msg.sent == ["✅ Готово"]


@pytest.mark.asyncio
async def test_safe_edit_falls_back_to_plain():
    msg = _FlakyMessage()
    await safe_edit(msg, f"{E.TIMER} Напомню завтра")
    assert msg.sent == ["⏲ Напомню завтра"]


@pytest.mark.asyncio
async def test_safe_bot_send_falls_back_to_plain():
    bot = _FlakyBot()
    await safe_bot_send(bot, 123, f"{E.TIMER} Напоминание по лиду <b>X</b>")
    assert bot.sent == ["⏲ Напоминание по лиду <b>X</b>"]


@pytest.mark.asyncio
async def test_safe_answer_no_fallback_needed():
    """Если Telegram принял сообщение с кастомными эмодзи — второй отправки нет."""
    class OkMessage:
        def __init__(self):
            self.calls = 0

        async def answer(self, text, **kwargs):
            self.calls += 1
            return text

    msg = OkMessage()
    await safe_answer(msg, f"{E.CHECK} Готово")
    assert msg.calls == 1
