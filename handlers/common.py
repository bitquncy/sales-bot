"""Глобальные команды и fallback-хендлеры."""

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from config import settings
from db import repo
from db.base import session_factory
from db.models import STATUS_LABELS
from keyboards.main_menu import main_menu_kb
from utils.emoji_config import E
from utils.safe_send import safe_answer

commands_router = Router(name="commands")
fallback_router = Router(name="fallback")

STATS_HELP_LINE = "/stats — статистика лидов и AI-расходов\n"

HELP_TEXT = (
    f"{E.INFO} Я AI Sales Agent: ищу компании, сохраняю лиды в CRM, "
    "делаю AI-анализ и помогаю подготовить первое сообщение.\n\n"
    "Команды:\n"
    "/start — открыть главное меню\n"
    "/help — показать эту подсказку\n"
    "/stats — статистика лидов и AI-расходов\n"
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


@commands_router.message(Command("stats"))
async def cmd_stats(message: Message) -> None:
    """Статистика лидов, источников, конверсии и LLM-расходов (AD-1)."""
    async with session_factory() as session:
        stats = await repo.get_stats(session, message.from_user.id)

    total = stats["total"]
    if total == 0:
        await safe_answer(message, f"{E.INFO} Лидов пока нет. Начни с поиска!", reply_markup=main_menu_kb())
        return

    lines = [f"<b>{E.CHART} Статистика</b>\n"]

    # Источники
    lines.append(f"<b>Лидов всего:</b> {total}")
    lines.append(f"  • OSM-поиск: {stats['osm']}")
    lines.append(f"  • Chat Monitor: {stats['chat_monitor']}")

    # Статусы
    lines.append("\n<b>По статусам:</b>")
    for status, label in STATUS_LABELS.items():
        count = stats["statuses"].get(status, 0)
        if count:
            lines.append(f"  • {label}: {count}")

    # Конверсия: new → client
    clients = stats["statuses"].get("client", 0)
    if total > 0:
        conv = round(clients / total * 100, 1)
        lines.append(f"\n<b>Конверсия</b> (new→client): {conv}%")

    # AI-расходы
    limit = settings.llm_daily_limit
    if limit > 0:
        lines.append(f"\n<b>AI-вызовов сегодня:</b> {stats['llm_today']}/{limit}")
    else:
        lines.append(f"\n<b>AI-вызовов сегодня:</b> {stats['llm_today']} (лимит не задан)")

    # Напоминания
    lines.append(f"<b>Активных напоминаний:</b> {stats['pending_reminders']}")

    await safe_answer(message, "\n".join(lines), reply_markup=main_menu_kb())


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
