"""Регрессии по QA-фиксам: fallback, cancel, лимиты Telegram, stale callbacks."""

from datetime import datetime

import pytest

import handlers.common as h_common
import handlers.crm as h_crm
import handlers.start as h_start
from db import repo
from handlers.company import format_lead_card
from states.fsm import SearchFSM
from tests.fakes import FakeCallback, FakeMessage, FakeState
from utils.safe_send import TELEGRAM_MESSAGE_LIMIT, safe_answer

OWNER = 555001


@pytest.fixture(autouse=True)
def _patch_session_factory(monkeypatch, session_factory):
    monkeypatch.setattr(h_start, "session_factory", session_factory)
    monkeypatch.setattr(h_crm, "session_factory", session_factory)


async def test_help_command_answers_with_menu():
    msg = FakeMessage(text="/help", user_id=OWNER)
    await h_common.cmd_help(msg)
    assert "/start" in msg.last_text()
    assert "/cancel" in msg.last_text()
    assert msg.log[-1][2] is not None


async def test_unknown_command_fallback_answers_with_hint():
    msg = FakeMessage(text="/asdasd", user_id=OWNER)
    await h_common.fallback_message(msg)
    assert "не нашёл подходящего действия" in msg.last_text()
    assert "/help" in msg.last_text()


async def test_plain_text_fallback_answers_with_hint():
    msg = FakeMessage(text="привет", user_id=OWNER)
    await h_common.fallback_message(msg)
    assert "Используй кнопки" in msg.last_text()
    assert msg.log[-1][2] is not None


async def test_start_clears_existing_fsm_state():
    state = FakeState(data={"city": "Казань"}, state=SearchFSM.waiting_category)
    msg = FakeMessage(text="/start", user_id=OWNER)
    await h_start.cmd_start(msg, state)
    assert state.state is None
    assert state.data == {}
    assert "AI Sales Agent" in msg.last_text()


async def test_start_existing_user_shows_returning_text():
    first = FakeMessage(text="/start", user_id=OWNER)
    await h_start.cmd_start(first, FakeState())

    second = FakeMessage(text="/start", user_id=OWNER)
    await h_start.cmd_start(second, FakeState())

    assert "С возвращением" in second.last_text()
    assert "Найду потенциальных клиентов" not in second.last_text()


async def test_cancel_active_state_clears_and_shows_menu():
    state = FakeState(data={"note_lead_id": 1}, state="NoteFSM:waiting_note")
    msg = FakeMessage(text="/cancel", user_id=OWNER)
    await h_common.cmd_cancel(msg, state)
    assert state.state is None
    assert state.data == {}
    assert "Действие отменено" in msg.last_text()
    assert msg.log[-1][2] is not None


async def test_cancel_without_state_says_nothing_to_cancel():
    state = FakeState()
    msg = FakeMessage(text="/cancel", user_id=OWNER)
    await h_common.cmd_cancel(msg, state)
    assert "Отменять нечего" in msg.last_text()
    assert msg.log[-1][2] is not None


class LengthCheckingMessage(FakeMessage):
    async def answer(self, text: str, reply_markup=None, **kwargs) -> "LengthCheckingMessage":
        assert len(text) <= TELEGRAM_MESSAGE_LIMIT
        self.log.append(("answer", text, reply_markup))
        return self


async def test_safe_answer_truncates_text_above_telegram_limit(session_factory):
    async with session_factory() as session:
        lead = await repo.create_lead(session, OWNER, "Очень длинный лид")
        lead = await repo.set_lead_note(session, lead.id, OWNER, "x" * (TELEGRAM_MESSAGE_LIMIT + 1000))

    msg = LengthCheckingMessage(user_id=OWNER)
    await safe_answer(msg, format_lead_card(lead))
    assert "текст обрезан" in msg.last_text()
    assert len(msg.last_text()) <= TELEGRAM_MESSAGE_LIMIT


async def test_stale_search_callbacks_show_alert():
    for callback_data in ("spg:1", "ssv:1", "san:1"):
        cb = FakeCallback(callback_data, OWNER)
        await h_common.stale_search_card_callback(cb)
        assert h_common.STALE_SEARCH_CARD_TEXT in cb.alert_texts()


async def test_chat_monitor_card_shows_source_chat_once(session_factory):
    async with session_factory() as session:
        lead = await repo.create_chat_lead(
            session,
            owner_tg_id=OWNER,
            source_chat="QA Chat Source",
            user_id=777,
            username=None,
            message_text="маникюр, есть свободное окошко",
            message_date=datetime(2026, 7, 10, 12, 30),
            relevance_score=0.9,
            llm_reasoning="релевантно",
            message_id=1,
        )

    card = format_lead_card(lead)
    assert card.count("QA Chat Source") == 1
    assert "Telegram user_id: 777" in card


async def test_leads_chat_monitor_filter_shows_only_chat_source(session_factory):
    async with session_factory() as session:
        await repo.create_lead(session, OWNER, "OSM Lead")
        await repo.create_chat_lead(
            session,
            owner_tg_id=OWNER,
            source_chat="QA Chat",
            user_id=888,
            username="nail_master",
            message_text="маникюр, принимаю на дому",
            message_date=datetime(2026, 7, 10, 12, 30),
            relevance_score=0.91,
            llm_reasoning="релевантно",
            message_id=2,
        )

    cb = FakeCallback("leads:chat_monitor", OWNER)
    await h_crm.list_leads_filtered(cb)
    assert "Лиды (Chat Monitor): 1" in cb.message.last_text()
    markup = cb.message.log[-1][2]
    btn_texts = [btn.text for row in markup.inline_keyboard for btn in row]
    assert any("@nail_master" in text for text in btn_texts)
    assert not any("OSM Lead" in text for text in btn_texts)
