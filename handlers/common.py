"""Глобальные команды и fallback-хендлеры."""

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from keyboards.main_menu import main_menu_kb
from utils.emoji_config import E
from utils.safe_send import safe_answer

commands_router = Router(name="commands")
fallback_router = Router(name="fallback")

HELP_TEXT = (
    f"{E.INFO} Я AI Sales Agent: ищу компании, сохраняю лиды в CRM, "
    "делаю AI-анализ и помогаю подготовить первое сообщение.\n\n"
    "Команды:\n"
    "/start — открыть главное меню\n"
    "/help — показать эту подсказку\n"
    "/cancel — отменить текущий сценарий\n\n"
    "Основные действия доступны кнопками в меню."
)

FALLBACK_TEXT = (
    f"{E.INFO} Я не нашёл подходящего действия.\n\n"
    "Используй кнопки в меню или команду /help, чтобы посмотреть возможности бота."
)

STALE_SEARCH_CARD_TEXT = "Эта карточка устарела, начните новый поиск."


@commands_router.message(Command("help"))
async def cmd_help(message: Message) -> None:
    await safe_answer(message, HELP_TEXT, reply_markup=main_menu_kb())


@commands_router.message(Command("cancel"))
async def cmd_cancel(message: Message, state: FSMContext) -> None:
    current_state = await state.get_state()
    await state.clear()
    prefix = "Действие отменено." if current_state else "Отменять нечего."
    await safe_answer(message, f"{E.CHECK} {prefix}\n\n{E.HOME} Главное меню:", reply_markup=main_menu_kb())


@fallback_router.callback_query(F.data.regexp(r"^(spg|ssv|san):"))
async def stale_search_card_callback(callback: CallbackQuery) -> None:
    await callback.answer(STALE_SEARCH_CARD_TEXT, show_alert=True)


@fallback_router.message()
async def fallback_message(message: Message) -> None:
    await safe_answer(message, FALLBACK_TEXT, reply_markup=main_menu_kb())
