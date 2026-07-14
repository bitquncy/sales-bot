"""Тесты генератора сообщений и HTML-экранирования."""

import json

import pytest

from handlers.messages import render_variants
from services.ai import AIError, AIRateLimitError, generate_messages
from tests.test_ai import FakeClient, _rate_limit_error


async def test_generate_messages_happy_path():
    payload = {"short": "Привет! Заметил, что у вас нет сайта.", "long": "Здравствуйте! " * 5}
    client = FakeClient(response_text=json.dumps(payload, ensure_ascii=False))
    short, long = await generate_messages("Барбершоп", "нет сайта", client=client)
    assert short == payload["short"]
    assert long == payload["long"].strip()


async def test_generate_messages_missing_variant_raises():
    client = FakeClient(response_text='{"short": "только короткое"}')
    with pytest.raises(AIError, match="empty message"):
        await generate_messages("X", "анализ", client=client)


async def test_generate_messages_invalid_json_raises():
    client = FakeClient(response_text="не json")
    with pytest.raises(AIError):
        await generate_messages("X", "анализ", client=client)


async def test_generate_messages_rate_limit():
    client = FakeClient(exc=_rate_limit_error())
    with pytest.raises(AIRateLimitError):
        await generate_messages("X", "анализ", client=client)


def test_render_variants_escapes_html_specials():
    """&, <, > в названии компании и текстах не ломают HTML-разметку."""
    out = render_variants('Кафе "Мама & Папа" <VIP>', "текст с <b> тегом", "и & амперсандом")
    assert "&amp;" in out
    assert "&lt;VIP&gt;" in out
    assert "<VIP>" not in out
    assert "&lt;b&gt;" in out
    assert "<b> тегом" not in out
    # Собственная разметка карточки при этом остаётся
    assert out.count("<pre>") == 2
