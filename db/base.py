"""Async engine, sessionmaker и инициализация схемы БД."""

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from config import settings


class Base(DeclarativeBase):
    pass


def create_engine(db_url: str | None = None) -> AsyncEngine:
    return create_async_engine(db_url or settings.db_url, echo=False)


engine: AsyncEngine = create_engine()
session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


def _ensure_lead_columns(conn) -> None:
    """Лёгкая миграция для УЖЕ существующих SQLite-БД.

    create_all создаёт только отсутствующие таблицы, но не добавляет новые
    колонки в существующие. Для личного бота без Alembic этого достаточно:
    досоздаём недостающие колонки в leads через ALTER TABLE ADD COLUMN.
    """
    from sqlalchemy import text

    existing = {row[1] for row in conn.execute(text("PRAGMA table_info(leads)"))}
    missing_columns = {
        "has_online_booking": "BOOLEAN",
        "niche": "VARCHAR(50)",
        "source_chat": "VARCHAR(500)",
        "chat_username": "VARCHAR(255)",
        "chat_user_id": "BIGINT",
        "chat_message_id": "BIGINT",
        "message_text": "TEXT",
        "message_date": "DATETIME",
        "relevance_score": "FLOAT",
    }
    for column, ddl in missing_columns.items():
        if existing and column not in existing:
            conn.execute(text(f"ALTER TABLE leads ADD COLUMN {column} {ddl}"))


async def init_db(target_engine: AsyncEngine | None = None) -> None:
    """Создаёт таблицы, если их нет, и досоздаёт недостающие колонки."""
    # Импорт моделей нужен, чтобы они зарегистрировались в metadata.
    from db import models  # noqa: F401

    eng = target_engine or engine
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.run_sync(_ensure_lead_columns)
