"""/start: регистрация пользователя и главное меню."""

from aiogram import Router
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from db import repo
from db.base import session_factory
from keyboards.main_menu import main_menu_kb
from utils.emoji_config import E
from utils.safe_send import safe_answer

router = Router(name="start")

START_NEW_TEXT = (
    f"{E.CLAP} Привет! Я твой AI Sales Agent.\n\n"
    f"{E.SEARCH} Найду потенциальных клиентов в твоём городе, "
    f"{E.CHART} проанализирую их "
    f"и {E.WRITING} помогу написать первое сообщение.\n\nВыбирай:"
)
START_RETURNING_TEXT = f"{E.CLAP} С возвращением! Главное меню:"


@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext | None = None) -> None:
    if state is not None:
        await state.clear()
    async with session_factory() as session:
        existing_user = await repo.get_user(session, message.from_user.id)
        await repo.get_or_create_user(
            session, tg_user_id=message.from_user.id, username=message.from_user.username
        )
    await safe_answer(
        message,
        START_RETURNING_TEXT if existing_user is not None else START_NEW_TEXT,
        reply_markup=main_menu_kb(),
    )
