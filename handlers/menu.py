"""Главное меню и заглушки."""

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery

from keyboards.main_menu import main_menu_kb
from utils.emoji_config import E
from utils.safe_send import safe_answer, safe_edit

router = Router(name="menu")


@router.callback_query(F.data == "menu:main")
async def show_main_menu(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await safe_edit(callback.message, f"{E.HOME} Главное меню:", reply_markup=main_menu_kb())
    await callback.answer()


@router.callback_query(F.data == "menu:settings")
async def show_settings(callback: CallbackQuery) -> None:
    await safe_answer(
        callback.message,
        f"{E.INFO} Настройки пока не требуются — бот работает из коробки.\n"
        "Токены задаются в файле .env.",
    )
    await callback.answer()


@router.callback_query(F.data == "noop")
async def noop(callback: CallbackQuery) -> None:
    await callback.answer()
