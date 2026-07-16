"""CRUD-операции. Все запросы к лидам/напоминаниям скоупятся по owner_tg_id."""

from datetime import datetime

from sqlalchemy import func, select, update
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from chat_monitor.config_store import (
    DEFAULT_MIN_SCORE,
    ChatMonitorConfig,
    deserialize_chat_refs,
    serialize_chat_refs,
)
from db.models import ChatMonitorSettings, LLMCallLog, Lead, Reminder, User, is_valid_status, utcnow


# ---------- User ----------

async def get_user(session: AsyncSession, tg_user_id: int) -> User | None:
    result = await session.execute(select(User).where(User.tg_user_id == tg_user_id))
    return result.scalar_one_or_none()


async def get_or_create_user(session: AsyncSession, tg_user_id: int, username: str | None = None) -> User:
    user = await get_user(session, tg_user_id)
    if user is None:
        user = User(tg_user_id=tg_user_id, username=username)
        session.add(user)
        await session.commit()
        await session.refresh(user)
    elif username and user.username != username:
        user.username = username
        await session.commit()
    return user


# ---------- Chat Monitor Settings ----------

def chat_monitor_settings_to_config(settings: ChatMonitorSettings) -> ChatMonitorConfig:
    return ChatMonitorConfig(
        owner_tg_id=settings.owner_tg_id,
        is_enabled=bool(settings.is_enabled),
        chats=deserialize_chat_refs(settings.chats),
        min_score=float(settings.min_score),
    )


async def get_or_create_chat_monitor_settings(
    session: AsyncSession,
    owner_tg_id: int,
    default_chats: list[str] | None = None,
    default_min_score: float = DEFAULT_MIN_SCORE,
) -> ChatMonitorSettings:
    result = await session.execute(
        select(ChatMonitorSettings).where(ChatMonitorSettings.owner_tg_id == owner_tg_id)
    )
    settings = result.scalar_one_or_none()
    if settings is None:
        settings = ChatMonitorSettings(
            owner_tg_id=owner_tg_id,
            chats=serialize_chat_refs(default_chats or []),
            min_score=default_min_score,
        )
        session.add(settings)
        await session.commit()
        await session.refresh(settings)
    return settings


async def save_chat_monitor_settings(
    session: AsyncSession,
    owner_tg_id: int,
    chats: list[str],
    min_score: float,
    is_enabled: bool,
) -> ChatMonitorSettings:
    settings = await get_or_create_chat_monitor_settings(session, owner_tg_id)
    settings.chats = serialize_chat_refs(chats)
    settings.min_score = min_score
    settings.is_enabled = is_enabled
    settings.updated_at = utcnow()
    await session.commit()
    await session.refresh(settings)
    return settings


async def add_chat_monitor_chats(
    session: AsyncSession,
    owner_tg_id: int,
    chats_to_add: list[str],
    default_chats: list[str] | None = None,
    default_min_score: float = DEFAULT_MIN_SCORE,
) -> ChatMonitorSettings:
    settings = await get_or_create_chat_monitor_settings(
        session, owner_tg_id, default_chats, default_min_score
    )
    chats = deserialize_chat_refs(settings.chats)
    for chat in chats_to_add:
        if chat not in chats:
            chats.append(chat)
    settings.chats = serialize_chat_refs(chats)
    settings.updated_at = utcnow()
    await session.commit()
    await session.refresh(settings)
    return settings


async def delete_chat_monitor_chat(
    session: AsyncSession,
    owner_tg_id: int,
    index: int,
) -> ChatMonitorSettings | None:
    settings = await get_or_create_chat_monitor_settings(session, owner_tg_id)
    chats = deserialize_chat_refs(settings.chats)
    if not 0 <= index < len(chats):
        return None
    del chats[index]
    settings.chats = serialize_chat_refs(chats)
    settings.updated_at = utcnow()
    await session.commit()
    await session.refresh(settings)
    return settings


async def set_chat_monitor_min_score(
    session: AsyncSession,
    owner_tg_id: int,
    min_score: float,
) -> ChatMonitorSettings:
    settings = await get_or_create_chat_monitor_settings(session, owner_tg_id)
    settings.min_score = min_score
    settings.updated_at = utcnow()
    await session.commit()
    await session.refresh(settings)
    return settings


async def toggle_chat_monitor_enabled(
    session: AsyncSession,
    owner_tg_id: int,
) -> ChatMonitorSettings:
    settings = await get_or_create_chat_monitor_settings(session, owner_tg_id)
    settings.is_enabled = not settings.is_enabled
    settings.updated_at = utcnow()
    await session.commit()
    await session.refresh(settings)
    return settings


# ---------- Lead ----------

async def create_lead(
    session: AsyncSession,
    owner_tg_id: int,
    name: str,
    address: str | None = None,
    phone: str | None = None,
    website: str | None = None,
    socials: str | None = None,
    source: str = "osm",
) -> Lead:
    lead = Lead(
        owner_tg_id=owner_tg_id,
        name=name,
        address=address,
        phone=phone,
        website=website,
        socials=socials,
        source=source,
    )
    session.add(lead)
    await session.commit()
    await session.refresh(lead)
    return lead


async def create_chat_lead(
    session: AsyncSession,
    owner_tg_id: int,
    source_chat: str,
    user_id: int,
    username: str | None,
    message_text: str,
    message_date: datetime,
    relevance_score: float,
    llm_reasoning: str,
    niche: str = "nail",
    message_id: int | None = None,
) -> Lead:
    """Сохраняет релевантное сообщение из Chat Lead Monitor в общую CRM."""
    normalized_username = username.lstrip("@") if username else None
    name = f"@{normalized_username}" if normalized_username else f"Telegram user {user_id}"
    lead = Lead(
        owner_tg_id=owner_tg_id,
        name=name,
        address=source_chat,
        website=f"https://t.me/{normalized_username}" if normalized_username else None,
        source="chat_monitor",
        ai_score=round(relevance_score * 100),
        ai_analysis=llm_reasoning,
        has_online_booking=False,
        niche=niche,
        source_chat=source_chat,
        chat_username=normalized_username,
        chat_user_id=user_id,
        chat_message_id=message_id,
        message_text=message_text,
        message_date=message_date,
        relevance_score=relevance_score,
    )
    session.add(lead)
    await session.commit()
    await session.refresh(lead)
    return lead


async def find_chat_lead_by_message(
    session: AsyncSession,
    owner_tg_id: int,
    source_chat: str,
    user_id: int,
    message_id: int | None,
) -> Lead | None:
    """Дедупликация повторной обработки одного Telegram-сообщения."""
    if message_id is None:
        return None
    result = await session.execute(
        select(Lead).where(
            Lead.owner_tg_id == owner_tg_id,
            Lead.source == "chat_monitor",
            Lead.source_chat == source_chat,
            Lead.chat_user_id == user_id,
            Lead.chat_message_id == message_id,
        )
    )
    return result.scalar_one_or_none()


async def find_lead_by_name_address(
    session: AsyncSession, owner_tg_id: int, name: str, address: str | None
) -> Lead | None:
    """Для дедупликации при повторном сохранении из поиска."""
    result = await session.execute(
        select(Lead).where(
            Lead.owner_tg_id == owner_tg_id,
            Lead.name == name,
            Lead.address == address,
        )
    )
    return result.scalars().first()


async def get_lead(session: AsyncSession, lead_id: int, owner_tg_id: int) -> Lead | None:
    result = await session.execute(
        select(Lead).where(Lead.id == lead_id, Lead.owner_tg_id == owner_tg_id)
    )
    return result.scalar_one_or_none()


PAGE_SIZE = 50  # Максимум лидов на одну страницу в UI


async def count_leads(
    session: AsyncSession,
    owner_tg_id: int,
    status: str | None = None,
    only_no_booking: bool = False,
    source: str | None = None,
) -> int:
    """Количество лидов по фильтру без загрузки строк."""
    query = select(func.count()).select_from(Lead).where(Lead.owner_tg_id == owner_tg_id)
    if status is not None:
        if not is_valid_status(status):
            raise ValueError(f"Invalid status filter: {status!r}")
        query = query.where(Lead.status == status)
    if only_no_booking:
        query = query.where(Lead.has_online_booking.is_(False))
    if source is not None:
        query = query.where(Lead.source == source)
    return (await session.execute(query)).scalar_one()


async def list_leads(
    session: AsyncSession,
    owner_tg_id: int,
    status: str | None = None,
    only_no_booking: bool = False,
    source: str | None = None,
    offset: int = 0,
    limit: int = PAGE_SIZE,
) -> list[Lead]:
    # Фильтры строятся ДО offset/limit — корректный порядок для SQL (CODE-2)
    query = select(Lead).where(Lead.owner_tg_id == owner_tg_id)
    if status is not None:
        if not is_valid_status(status):
            raise ValueError(f"Invalid status filter: {status!r}")
        query = query.where(Lead.status == status)
    if only_no_booking:
        # Только явное False. None (не анализировали/не определили) НЕ попадает —
        # это не «нет записи», а «неизвестно».
        query = query.where(Lead.has_online_booking.is_(False))
    if source is not None:
        query = query.where(Lead.source == source)
    query = query.order_by(Lead.updated_at.desc()).offset(offset).limit(limit)
    result = await session.execute(query)
    return list(result.scalars().all())


async def set_lead_status(
    session: AsyncSession, lead_id: int, owner_tg_id: int, status: str
) -> Lead | None:
    """Меняет статус. Невалидный статус -> ValueError (хендлер покажет user-friendly текст)."""
    if not is_valid_status(status):
        raise ValueError(f"Invalid status: {status!r}")
    lead = await get_lead(session, lead_id, owner_tg_id)
    if lead is None:
        return None
    lead.status = status
    lead.updated_at = utcnow()
    await session.commit()
    await session.refresh(lead)
    return lead


async def set_lead_note(
    session: AsyncSession, lead_id: int, owner_tg_id: int, note: str
) -> Lead | None:
    lead = await get_lead(session, lead_id, owner_tg_id)
    if lead is None:
        return None
    lead.note = note
    lead.updated_at = utcnow()
    await session.commit()
    await session.refresh(lead)
    return lead


async def save_lead_analysis(
    session: AsyncSession,
    lead_id: int,
    owner_tg_id: int,
    score: int,
    analysis: str,
    has_online_booking: bool | None = None,
) -> Lead | None:
    lead = await get_lead(session, lead_id, owner_tg_id)
    if lead is None:
        return None
    lead.ai_score = score
    lead.ai_analysis = analysis
    lead.has_online_booking = has_online_booking
    lead.updated_at = utcnow()
    await session.commit()
    await session.refresh(lead)
    return lead


# ---------- Reminder ----------

async def create_reminder(
    session: AsyncSession, lead_id: int, owner_tg_id: int, remind_at: datetime, text: str = ""
) -> Reminder:
    reminder = Reminder(lead_id=lead_id, owner_tg_id=owner_tg_id, remind_at=remind_at, text=text)
    session.add(reminder)
    await session.commit()
    await session.refresh(reminder)
    return reminder


async def get_due_reminders(session: AsyncSession, now: datetime | None = None) -> list[Reminder]:
    """Возвращает просроченные напоминания с предзагрузкой лида (устраняет N+1, CODE-3)."""
    now = now or utcnow()
    result = await session.execute(
        select(Reminder)
        .options(selectinload(Reminder.lead))
        .where(Reminder.remind_at <= now, Reminder.is_sent.is_(False))
    )
    return list(result.scalars().all())


async def _set_reminder_sent(session: AsyncSession, reminder_id: int, value: bool) -> None:
    """Один UPDATE вместо SELECT + UPDATE (CODE-4)."""
    await session.execute(
        update(Reminder).where(Reminder.id == reminder_id).values(is_sent=value)
    )
    await session.commit()


async def mark_reminder_sent(session: AsyncSession, reminder_id: int) -> None:
    await _set_reminder_sent(session, reminder_id, True)


async def mark_reminder_unsent(session: AsyncSession, reminder_id: int) -> None:
    """Откат при сбое отправки — напоминание будет переотправлено поллером."""
    await _set_reminder_sent(session, reminder_id, False)


# ---------- LLM Call Logging (P-2) ----------

async def log_llm_call(session: AsyncSession) -> None:
    """Записывает факт LLM-вызова в журнал."""
    session.add(LLMCallLog())
    await session.commit()


async def count_today_llm_calls(session: AsyncSession) -> int:
    """Количество LLM-вызовов за сегодня (UTC). Использует COUNT(*) — не загружает строки."""
    today_start = utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    result = await session.execute(
        select(func.count()).select_from(LLMCallLog).where(LLMCallLog.created_at >= today_start)
    )
    return result.scalar_one()


async def check_llm_budget(
    session: AsyncSession, daily_limit: int = 0
) -> tuple[bool, int]:
    """Проверяет, не превышен ли дневной лимит LLM-вызовов.

    Возвращает (разрешено, текущее_количество_вызовов).
    Если daily_limit <= 0 — лимит отключён, всегда разрешено.
    Логирует вызов только если разрешено.
    """
    count = await count_today_llm_calls(session)
    if daily_limit > 0 and count >= daily_limit:
        return False, count
    await log_llm_call(session)
    return True, count + 1


# ---------- Delete Lead (P-6 / audit 11.14) ----------

async def delete_lead(session: AsyncSession, lead_id: int, owner_tg_id: int) -> bool:
    """Удаляет лид и связанные напоминания атомарно. True если удалён.

    Каскадное удаление напоминаний обеспечивается relationship(cascade="all, delete-orphan")
    в модели Lead — нет риска «висячих» напоминаний при сбое между операциями (CODE-1).
    """
    lead = await get_lead(session, lead_id, owner_tg_id)
    if lead is None:
        return False
    await session.delete(lead)
    await session.commit()
    return True


async def list_reminders_for_lead(
    session: AsyncSession, lead_id: int, owner_tg_id: int
) -> list[Reminder]:
    """Список напоминаний для лида."""
    result = await session.execute(
        select(Reminder).where(
            Reminder.lead_id == lead_id,
            Reminder.owner_tg_id == owner_tg_id,
        ).order_by(Reminder.remind_at)
    )
    return list(result.scalars().all())


async def delete_reminder(
    session: AsyncSession, reminder_id: int, owner_tg_id: int
) -> bool:
    """Удаляет напоминание. True если удалено."""
    result = await session.execute(
        select(Reminder).where(
            Reminder.id == reminder_id,
            Reminder.owner_tg_id == owner_tg_id,
        )
    )
    reminder = result.scalar_one_or_none()
    if reminder is None:
        return False
    await session.delete(reminder)
    await session.commit()
    return True


# ---------- Stats (AD-1) ----------

async def get_stats(session: AsyncSession, owner_tg_id: int) -> dict:
    """Агрегированная статистика для команды /stats.

    Оптимизировано: 3 запроса вместо 5 (ARCH-6).
    Источники и статусы получаются через GROUP BY, а не отдельными COUNT.
    """
    # Запрос 1: количество лидов по статусам (один GROUP BY вместо N запросов)
    status_rows = (await session.execute(
        select(Lead.status, func.count())
        .where(Lead.owner_tg_id == owner_tg_id)
        .group_by(Lead.status)
    )).all()
    statuses = {row[0]: row[1] for row in status_rows}
    total = sum(statuses.values())

    # Запрос 2: количество лидов по источникам (один GROUP BY)
    source_rows = (await session.execute(
        select(Lead.source, func.count())
        .where(Lead.owner_tg_id == owner_tg_id)
        .group_by(Lead.source)
    )).all()
    sources = {row[0]: row[1] for row in source_rows}

    # Запрос 3: LLM-вызовы сегодня + активные напоминания (два лёгких COUNT)
    llm_today = await count_today_llm_calls(session)
    pending_reminders = (await session.execute(
        select(func.count()).select_from(Reminder).where(
            Reminder.owner_tg_id == owner_tg_id, Reminder.is_sent.is_(False)
        )
    )).scalar_one()

    return {
        "total": total,
        "osm": sources.get("osm", 0),
        "chat_monitor": sources.get("chat_monitor", 0),
        "statuses": statuses,
        "llm_today": llm_today,
        "pending_reminders": pending_reminders,
    }
