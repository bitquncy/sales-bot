"""CRUD-операции. Все запросы к лидам/напоминаниям скоупятся по owner_tg_id."""

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from chat_monitor.config_store import (
    DEFAULT_MIN_SCORE,
    ChatMonitorConfig,
    deserialize_chat_refs,
    serialize_chat_refs,
)
from db.models import ChatMonitorSettings, Lead, Reminder, User, is_valid_status, utcnow


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


async def list_leads(
    session: AsyncSession,
    owner_tg_id: int,
    status: str | None = None,
    only_no_booking: bool = False,
    source: str | None = None,
) -> list[Lead]:
    query = select(Lead).where(Lead.owner_tg_id == owner_tg_id).order_by(Lead.updated_at.desc())
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
    now = now or utcnow()
    result = await session.execute(
        select(Reminder).where(Reminder.remind_at <= now, Reminder.is_sent.is_(False))
    )
    return list(result.scalars().all())


async def _set_reminder_sent(session: AsyncSession, reminder_id: int, value: bool) -> None:
    result = await session.execute(select(Reminder).where(Reminder.id == reminder_id))
    reminder = result.scalar_one_or_none()
    if reminder is not None:
        reminder.is_sent = value
        await session.commit()


async def mark_reminder_sent(session: AsyncSession, reminder_id: int) -> None:
    await _set_reminder_sent(session, reminder_id, True)


async def mark_reminder_unsent(session: AsyncSession, reminder_id: int) -> None:
    """Откат при сбое отправки — напоминание будет переотправлено поллером."""
    await _set_reminder_sent(session, reminder_id, False)
