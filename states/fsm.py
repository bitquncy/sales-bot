"""FSM-состояния бота."""

from aiogram.fsm.state import State, StatesGroup


class SearchFSM(StatesGroup):
    waiting_city = State()
    waiting_category = State()
    browsing = State()


class NoteFSM(StatesGroup):
    waiting_note = State()


class EditMessageFSM(StatesGroup):
    waiting_text = State()


class ReminderFSM(StatesGroup):
    waiting_date = State()


class ChatMonitorFSM(StatesGroup):
    waiting_chat = State()
    waiting_threshold = State()
