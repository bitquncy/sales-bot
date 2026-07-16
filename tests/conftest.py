"""Общие фикстуры: in-memory SQLite на каждый тест, без сети."""

import pytest
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from db.base import Base, _set_sqlite_pragma
from db import models  # noqa: F401  (регистрация моделей в metadata)


@pytest.fixture
async def engine():
    eng = create_async_engine("sqlite+aiosqlite:///:memory:")
    # Включаем FK и pragma — те же настройки что в production (CODE-1)
    event.listen(eng.sync_engine, "connect", _set_sqlite_pragma)
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield eng
    await eng.dispose()


@pytest.fixture
async def session_factory(engine):
    return async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


@pytest.fixture
async def session(session_factory):
    async with session_factory() as s:
        yield s
