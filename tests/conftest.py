"""Общие фикстуры: in-memory SQLite на каждый тест, без сети."""

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from db.base import Base
from db import models  # noqa: F401  (регистрация моделей в metadata)


@pytest.fixture
async def engine():
    eng = create_async_engine("sqlite+aiosqlite:///:memory:")
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
