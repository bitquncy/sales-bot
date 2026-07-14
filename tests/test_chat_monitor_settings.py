"""Тесты настроек Chat Monitor через бот и runtime runner."""

import pytest

import handlers.chat_monitor as h_cm
from chat_monitor.config_store import deserialize_chat_refs, parse_chat_refs, parse_min_score
from chat_monitor.runner import event_matches_chat_refs, normalize_phone
from db import repo
from keyboards.main_menu import main_menu_kb
from states.fsm import ChatMonitorFSM
from tests.fakes import FakeCallback, FakeMessage, FakeState

OWNER = 606060


@pytest.fixture(autouse=True)
def _patch_session_factory(monkeypatch, session_factory):
    monkeypatch.setattr(h_cm, "session_factory", session_factory)
    monkeypatch.setattr(h_cm.settings, "chat_monitor_chats", "")
    monkeypatch.setattr(h_cm.settings, "chat_monitor_min_score", 0.7)
    monkeypatch.setattr(h_cm.settings, "chat_monitor_owner_tg_id", OWNER)
    monkeypatch.setattr(h_cm.settings, "chat_monitor_api_id", 123)
    monkeypatch.setattr(h_cm.settings, "chat_monitor_api_hash", "hash")
    monkeypatch.setattr(h_cm.settings, "chat_monitor_phone", "+70000000000")
    monkeypatch.setattr(h_cm.settings, "chat_monitor_session_path", "test.session")


def _button_datas(kb):
    return [btn.callback_data for row in kb.inline_keyboard for btn in row]


def test_main_menu_has_chat_monitor_button():
    assert "menu:chat_monitor" in _button_datas(main_menu_kb())


def test_parse_chat_refs_accepts_usernames_ids_and_links():
    refs = parse_chat_refs("@nails, -100123, https://t.me/open_chat")
    assert refs == ["@nails", "-100123", "@open_chat"]


def test_parse_min_score_validation():
    assert parse_min_score("0,75") == 0.75
    assert parse_min_score("1.1") is None
    assert parse_min_score("abc") is None


def test_normalize_phone_removes_spaces_and_punctuation():
    assert normalize_phone("+7 771 430 0027") == "+77714300027"
    assert normalize_phone("8 (771) 430-00-27") == "87714300027"


async def test_repo_chat_monitor_settings_crud(session):
    row = await repo.get_or_create_chat_monitor_settings(session, OWNER, ["@seed"], 0.8)
    assert deserialize_chat_refs(row.chats) == ["@seed"]
    assert row.min_score == 0.8

    row = await repo.add_chat_monitor_chats(session, OWNER, ["@seed", "@new"])
    assert deserialize_chat_refs(row.chats) == ["@seed", "@new"]

    row = await repo.set_chat_monitor_min_score(session, OWNER, 0.6)
    assert row.min_score == 0.6

    row = await repo.toggle_chat_monitor_enabled(session, OWNER)
    assert row.is_enabled is False

    row = await repo.delete_chat_monitor_chat(session, OWNER, 0)
    assert deserialize_chat_refs(row.chats) == ["@new"]


async def test_chat_monitor_menu_shows_status_and_buttons():
    cb = FakeCallback("menu:chat_monitor", OWNER)
    state = FakeState(data={"junk": 1}, state="x")
    await h_cm.show_chat_monitor_menu(cb, state)
    assert state.state is None
    assert "Chat Monitor" in cb.message.last_text()
    assert cb.message.log[-1][2] is not None


async def test_add_chat_flow_saves_refs(session_factory):
    state = FakeState()
    cb = FakeCallback("cm:add", OWNER)
    await h_cm.add_chat_start(cb, state)
    assert state.state == ChatMonitorFSM.waiting_chat

    msg = FakeMessage(text="@nails, -100123", user_id=OWNER)
    await h_cm.add_chat_received(msg, state)
    assert state.state is None
    async with session_factory() as session:
        row = await repo.get_or_create_chat_monitor_settings(session, OWNER)
    assert deserialize_chat_refs(row.chats) == ["@nails", "-100123"]


async def test_add_chat_invalid_reasks():
    state = FakeState(state=ChatMonitorFSM.waiting_chat)
    msg = FakeMessage(text=" , ", user_id=OWNER)
    await h_cm.add_chat_received(msg, state)
    assert state.state == ChatMonitorFSM.waiting_chat
    assert "Не нашёл" in msg.last_text()


async def test_threshold_flow_validates_and_saves(session_factory):
    state = FakeState()
    await h_cm.threshold_start(FakeCallback("cm:threshold", OWNER), state)
    assert state.state == ChatMonitorFSM.waiting_threshold

    bad = FakeMessage(text="2", user_id=OWNER)
    await h_cm.threshold_received(bad, state)
    assert state.state == ChatMonitorFSM.waiting_threshold
    assert "от 0 до 1" in bad.last_text()

    ok = FakeMessage(text="0.65", user_id=OWNER)
    await h_cm.threshold_received(ok, state)
    assert state.state is None
    async with session_factory() as session:
        row = await repo.get_or_create_chat_monitor_settings(session, OWNER)
    assert row.min_score == 0.65


async def test_delete_chat_button_removes_by_index(session_factory):
    async with session_factory() as session:
        await repo.add_chat_monitor_chats(session, OWNER, ["@one", "@two"])
    cb = FakeCallback("cm:del:0", OWNER)
    await h_cm.delete_chat(cb)
    async with session_factory() as session:
        row = await repo.get_or_create_chat_monitor_settings(session, OWNER)
    assert deserialize_chat_refs(row.chats) == ["@two"]


async def test_toggle_monitor_changes_enabled(session_factory):
    cb = FakeCallback("cm:toggle", OWNER)
    await h_cm.toggle_monitor(cb)
    async with session_factory() as session:
        row = await repo.get_or_create_chat_monitor_settings(session, OWNER)
    assert row.is_enabled is False


class FakeChat:
    def __init__(self, username=None):
        self.username = username


class FakeEvent:
    def __init__(self, chat_id, username=None):
        self.chat_id = chat_id
        self._chat = FakeChat(username)

    async def get_chat(self):
        return self._chat


async def test_runner_event_matches_chat_refs_by_id_and_username():
    assert await event_matches_chat_refs(FakeEvent(-100123), ["-100123"])
    assert await event_matches_chat_refs(FakeEvent(-100999, "nails"), ["@nails"])
    assert not await event_matches_chat_refs(FakeEvent(-100999, "other"), ["@nails"])
