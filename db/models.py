"""Модели БД: User, Lead, Reminder, ChatMonitorSettings."""

import enum
from datetime import datetime, timezone

from sqlalchemy import BigInteger, Boolean, DateTime, Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from db.base import Base


def utcnow() -> datetime:
    """Наивный UTC (SQLite хранит naive datetime)."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


class LeadStatus(str, enum.Enum):
    new = "new"
    written = "written"
    replied = "replied"
    client = "client"
    rejected = "rejected"


VALID_STATUSES: frozenset[str] = frozenset(s.value for s in LeadStatus)

STATUS_LABELS: dict[str, str] = {
    "new": "Новый",
    "written": "Написали",
    "replied": "Ответил",
    "client": "Клиент",
    "rejected": "Отказ",
}


def is_valid_status(value: str) -> bool:
    return value in VALID_STATUSES


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tg_user_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True)
    username: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class Lead(Base):
    __tablename__ = "leads"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    owner_tg_id: Mapped[int] = mapped_column(BigInteger, index=True)
    name: Mapped[str] = mapped_column(String(500))
    address: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(100), nullable=True)
    website: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    # JSON-строка; почти всегда пусто — OSM соцсети практически не отдаёт
    socials: Mapped[str | None] = mapped_column(Text, nullable=True)
    source: Mapped[str] = mapped_column(String(50), default="osm", index=True)
    ai_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    ai_analysis: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Есть ли у компании онлайн-запись (по AI-анализу):
    #   True  — найдены признаки (виджет/форма/YCLIENTS/Fresha/…);
    #   False — сайта нет ИЛИ признаков нет -> возможность для оффера;
    #   None  — не анализировали или определить не удалось (не «да» и не «нет»).
    has_online_booking: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    # Chat Lead Monitor расширяет общую таблицу leads, а не заводит отдельную,
    # чтобы переиспользовать существующую CRM: статусы, заметки, напоминания и
    # генерацию сообщений. Для OSM-лидов эти поля остаются NULL.
    niche: Mapped[str | None] = mapped_column(String(50), nullable=True, index=True)
    source_chat: Mapped[str | None] = mapped_column(String(500), nullable=True)
    chat_username: Mapped[str | None] = mapped_column(String(255), nullable=True)
    chat_user_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True, index=True)
    chat_message_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True, index=True)
    message_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    message_date: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    relevance_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    status: Mapped[str] = mapped_column(String(16), default=LeadStatus.new.value, index=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow, onupdate=utcnow)

    # Каскадное удаление напоминаний при удалении лида (CODE-1)
    reminders: Mapped[list["Reminder"]] = relationship(
        "Reminder", back_populates="lead", cascade="all, delete-orphan", passive_deletes=True
    )

    # Составной индекс для быстрой дедупликации chat-лидов (DB-2)
    __table_args__ = (
        Index(
            "ix_chat_lead_dedup",
            "owner_tg_id", "source_chat", "chat_user_id", "chat_message_id",
        ),
    )


class Reminder(Base):
    __tablename__ = "reminders"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    lead_id: Mapped[int] = mapped_column(ForeignKey("leads.id", ondelete="CASCADE"), index=True)
    owner_tg_id: Mapped[int] = mapped_column(BigInteger, index=True)
    remind_at: Mapped[datetime] = mapped_column(index=True)
    text: Mapped[str] = mapped_column(Text, default="")
    is_sent: Mapped[bool] = mapped_column(default=False, index=True)

    lead: Mapped["Lead"] = relationship("Lead", back_populates="reminders")


class LLMCallLog(Base):
    """Журнал LLM-вызовов для контроля дневного бюджета (P-2)."""

    __tablename__ = "llm_call_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    created_at: Mapped[datetime] = mapped_column(default=utcnow, index=True)


class ChatMonitorSettings(Base):
    __tablename__ = "chat_monitor_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    owner_tg_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True)
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    # JSON-массив строк: usernames (@chat) или числовые chat_id.
    # Секреты Telethon намеренно не храним в БД и не вводим через бота.
    chats: Mapped[str] = mapped_column(Text, default="[]")
    min_score: Mapped[float] = mapped_column(Float, default=0.7)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow, onupdate=utcnow)
