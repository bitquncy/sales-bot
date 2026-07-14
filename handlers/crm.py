"""Этапы 5-6: CRM-лайт (лиды, статусы, заметки) и напоминания."""

import logging
from datetime import datetime, timedelta
from html import escape

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from db import repo
from db.base import session_factory
from db.models import STATUS_LABELS, is_valid_status, utcnow
from handlers.company import format_lead_card
from keyboards.main_menu import lead_card_kb, leads_filter_kb, reminder_kb, statuses_kb
from states.fsm import NoteFSM, ReminderFSM
from utils.emoji_config import E, P
from utils.safe_send import safe_answer, safe_edit

logger = logging.getLogger(__name__)
router = Router(name="crm")

MSG_INVALID_STATUS = f"{P.CROSS} Такого статуса не существует. Выбери статус кнопкой из списка."
MSG_BAD_DATA = f"{P.CROSS} Некорректные данные. Попробуй ещё раз."
MSG_LEAD_NOT_FOUND = f"{P.CROSS} Лид не найден."


def parse_custom_date(raw: str) -> datetime | None:
    """Парсит 'ДД.ММ.ГГГГ ЧЧ:ММ' или 'ДД.ММ.ГГГГ' (тогда 10:00). None — если невалидно."""
    raw = raw.strip()
    for fmt in ("%d.%m.%Y %H:%M", "%d.%m.%Y"):
        try:
            dt = datetime.strptime(raw, fmt)
            if fmt == "%d.%m.%Y":
                dt = dt.replace(hour=10, minute=0)
            return dt
        except ValueError:
            continue
    return None


# ---------- Список лидов ----------

@router.callback_query(F.data == "menu:leads")
async def show_leads_menu(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await safe_answer(
        callback.message, f"{E.LIST} Мои лиды. Выбери фильтр по статусу:", reply_markup=leads_filter_kb()
    )
    await callback.answer()


@router.callback_query(F.data.startswith("leads:"))
async def list_leads_filtered(callback: CallbackQuery) -> None:
    raw_filter = callback.data.split(":", 1)[1]

    if raw_filter == "no_booking":
        # Спец-фильтр: проанализированные лиды без онлайн-записи (самые перспективные).
        async with session_factory() as session:
            leads = await repo.list_leads(
                session, callback.from_user.id, only_no_booking=True
            )
        label = "Без онлайн-записи"
    elif raw_filter == "chat_monitor":
        async with session_factory() as session:
            leads = await repo.list_leads(
                session, callback.from_user.id, source="chat_monitor"
            )
        label = "Chat Monitor"
    else:
        status = None if raw_filter == "all" else raw_filter
        if status is not None and not is_valid_status(status):
            await callback.answer(MSG_INVALID_STATUS, show_alert=True)
            return
        async with session_factory() as session:
            leads = await repo.list_leads(session, callback.from_user.id, status)
        label = "Все" if status is None else STATUS_LABELS[status]
    if not leads:
        await safe_answer(
            callback.message,
            f"{E.INFO} По фильтру «{label}» лидов пока нет.\n"
            "Начни с поиска — «Новый поиск» в меню.",
        )
        await callback.answer()
        return

    rows = [
        [InlineKeyboardButton(
            text=f"{lead.name[:40]} · {STATUS_LABELS.get(lead.status, lead.status)}",
            callback_data=f"lead:{lead.id}",
        )]
        for lead in leads[:50]
    ]
    rows.append([InlineKeyboardButton(text="↩ Фильтры", callback_data="menu:leads")])
    await safe_answer(
        callback.message,
        f"{E.PEOPLE} Лиды ({label}): {len(leads)}",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("lead:"))
async def show_lead_card(callback: CallbackQuery, state: FSMContext) -> None:
    try:
        lead_id = int(callback.data.split(":", 1)[1])
    except ValueError:
        await callback.answer(MSG_BAD_DATA, show_alert=True)
        return
    async with session_factory() as session:
        lead = await repo.get_lead(session, lead_id, callback.from_user.id)
    if lead is None:
        await callback.answer(MSG_LEAD_NOT_FOUND, show_alert=True)
        return
    await safe_answer(
        callback.message,
        format_lead_card(lead),
        reply_markup=lead_card_kb(lead.id, has_analysis=bool(lead.ai_analysis)),
    )
    await callback.answer()


# ---------- Статусы ----------

@router.callback_query(F.data.startswith("sts:"))
async def change_status(callback: CallbackQuery) -> None:
    parts = callback.data.split(":")
    if len(parts) != 3:
        await callback.answer(MSG_BAD_DATA, show_alert=True)
        return
    try:
        lead_id = int(parts[1])
    except ValueError:
        await callback.answer(MSG_BAD_DATA, show_alert=True)
        return
    status = parts[2]
    # Явная проверка невалидного статуса (в т.ч. модифицированный callback)
    if not is_valid_status(status):
        await callback.answer(MSG_INVALID_STATUS, show_alert=True)
        return

    async with session_factory() as session:
        try:
            lead = await repo.set_lead_status(session, lead_id, callback.from_user.id, status)
        except ValueError:
            await callback.answer(MSG_INVALID_STATUS, show_alert=True)
            return
    if lead is None:
        await callback.answer(MSG_LEAD_NOT_FOUND, show_alert=True)
        return
    await safe_edit(
        callback.message,
        format_lead_card(lead),
        reply_markup=lead_card_kb(lead.id, has_analysis=bool(lead.ai_analysis)),
    )
    await callback.answer(f"{P.CHECK} Статус: {STATUS_LABELS[status]}")


@router.callback_query(F.data.startswith("st:"))
async def status_menu(callback: CallbackQuery) -> None:
    try:
        lead_id = int(callback.data.split(":", 1)[1])
    except ValueError:
        await callback.answer(MSG_BAD_DATA, show_alert=True)
        return
    await callback.message.edit_reply_markup(reply_markup=statuses_kb(lead_id))
    await callback.answer()


# ---------- Заметки ----------

@router.callback_query(F.data.startswith("note:"))
async def note_start(callback: CallbackQuery, state: FSMContext) -> None:
    try:
        lead_id = int(callback.data.split(":", 1)[1])
    except ValueError:
        await callback.answer(MSG_BAD_DATA, show_alert=True)
        return
    async with session_factory() as session:
        lead = await repo.get_lead(session, lead_id, callback.from_user.id)
    if lead is None:
        await callback.answer(MSG_LEAD_NOT_FOUND, show_alert=True)
        return
    current = f"Текущая заметка:\n<i>{escape(lead.note)}</i>\n\n" if lead.note else ""
    await state.set_state(NoteFSM.waiting_note)
    await state.update_data(note_lead_id=lead_id)
    await safe_answer(callback.message, f"{current}{E.NOTE} Пришли текст новой заметки:")
    await callback.answer()


@router.message(NoteFSM.waiting_note)
async def note_received(message: Message, state: FSMContext) -> None:
    text = (message.text or "").strip()
    if not text:
        await message.answer("Пустая заметка не сохранится. Пришли текст.")
        return
    data = await state.get_data()
    lead_id = data.get("note_lead_id")
    async with session_factory() as session:
        lead = await repo.set_lead_note(session, lead_id, message.from_user.id, text)
    await state.clear()
    if lead is None:
        await safe_answer(message, f"{E.CROSS} Лид не найден.")
        return
    await safe_answer(
        message,
        format_lead_card(lead),
        reply_markup=lead_card_kb(lead.id, has_analysis=bool(lead.ai_analysis)),
    )


# ---------- Напоминания ----------

@router.callback_query(F.data.startswith("remd:"))
async def reminder_days(callback: CallbackQuery) -> None:
    parts = callback.data.split(":")
    if len(parts) != 3:
        await callback.answer(MSG_BAD_DATA, show_alert=True)
        return
    try:
        lead_id = int(parts[1])
        days = int(parts[2])
    except ValueError:
        await callback.answer(MSG_BAD_DATA, show_alert=True)
        return
    if days not in (1, 3, 7, 14):
        await callback.answer(f"{P.CROSS} Некорректный интервал. Выбери кнопкой.", show_alert=True)
        return

    async with session_factory() as session:
        lead = await repo.get_lead(session, lead_id, callback.from_user.id)
        if lead is None:
            await callback.answer(MSG_LEAD_NOT_FOUND, show_alert=True)
            return
        remind_at = utcnow() + timedelta(days=days)
        await repo.create_reminder(
            session, lead_id, callback.from_user.id, remind_at, text=f"Пора связаться: {lead.name}"
        )
    await callback.answer(f"{P.CHECK} Напомню через {days} дн.", show_alert=False)


@router.callback_query(F.data.startswith("remc:"))
async def reminder_custom_start(callback: CallbackQuery, state: FSMContext) -> None:
    try:
        lead_id = int(callback.data.split(":", 1)[1])
    except ValueError:
        await callback.answer(MSG_BAD_DATA, show_alert=True)
        return
    await state.set_state(ReminderFSM.waiting_date)
    await state.update_data(reminder_lead_id=lead_id)
    await safe_answer(
        callback.message,
        f"{E.CALENDAR} Пришли дату в формате <b>ДД.ММ.ГГГГ ЧЧ:ММ</b> "
        "(или только дату — напомню в 10:00).\nВремя — по UTC.",
    )
    await callback.answer()


@router.message(ReminderFSM.waiting_date)
async def reminder_custom_received(message: Message, state: FSMContext) -> None:
    dt = parse_custom_date(message.text or "")
    if dt is None:
        await message.answer("Не понял дату. Формат: 25.12.2026 15:30 или 25.12.2026")
        return
    if dt <= utcnow():
        await message.answer("Эта дата уже в прошлом. Пришли дату в будущем.")
        return
    data = await state.get_data()
    lead_id = data.get("reminder_lead_id")
    async with session_factory() as session:
        lead = await repo.get_lead(session, lead_id, message.from_user.id)
        if lead is None:
            await state.clear()
            await safe_answer(message, f"{E.CROSS} Лид не найден.")
            return
        await repo.create_reminder(
            session, lead_id, message.from_user.id, dt, text=f"Пора связаться: {lead.name}"
        )
    await state.clear()
    await safe_answer(
        message, f"{E.TIMER} Напомню {dt.strftime('%d.%m.%Y %H:%M')} (UTC) {E.CHECK}"
    )


@router.callback_query(F.data.startswith("rem:"))
async def reminder_menu(callback: CallbackQuery) -> None:
    try:
        lead_id = int(callback.data.split(":", 1)[1])
    except ValueError:
        await callback.answer(MSG_BAD_DATA, show_alert=True)
        return
    await safe_answer(
        callback.message, f"{E.TIMER} Когда напомнить об этом лиде?", reply_markup=reminder_kb(lead_id)
    )
    await callback.answer()
