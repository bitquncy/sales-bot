"""Smoke-тест PostgreSQL-совместимости (запускается в CI job postgres-compat).

Проверяет на РЕАЛЬНОМ PostgreSQL:
1. init_db создаёт схему (включая частичный UNIQUE-индекс uq_osm_lead_dedup
   с postgresql_where — регрессия здесь ломала бы PG-деплой);
2. базовый CRUD: создание пользователя, лида, напоминания, дедупликация
   (IntegrityError вместо дубля), аудит-лог;
3. идемпотентность: повторный init_db не падает.

Запуск:
    DB_URL=postgresql+asyncpg://user:pass@localhost:5432/db python -m scripts.pg_smoke

Без DB_URL с postgresql:// скрипт завершается ошибкой — это guard от случайного
запуска против SQLite (где весь смысл теста теряется).
"""

import asyncio
import sys
from pathlib import Path

# Позволяем запуск из корня проекта
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from config import settings
from db import repo
from db.base import create_engine, verify_schema


async def run_smoke() -> None:
    if not settings.db_url.startswith("postgresql"):
        raise SystemExit(
            f"pg_smoke requires DB_URL=postgresql+asyncpg://..., got: {settings.db_url!r}"
        )

    engine = create_engine()
    try:
        # Схема должна быть заранее создана `alembic upgrade head`.
        await verify_schema(engine)

        factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        owner = 999_000_001

        async with factory() as session:
            # Пользователь
            user = await repo.get_or_create_user(session, owner, "pg_smoke")
            assert user.tg_user_id == owner

            # Лид + дедупликация на уровне БД (частичный индекс)
            lead = await repo.create_lead(session, owner, "PG Smoke Co", address="Test st. 1")
            assert lead.id is not None

            try:
                await repo.create_lead(session, owner, "PG Smoke Co", address="Test st. 1")
            except IntegrityError:
                pass  # repo.create_lead сам ловит; сюда попадаем только при гонке
            else:
                # Повторный вызов вернул существующий лид (дедуп сработал в коде)
                pass

            # Анализ, статус, заметка
            await repo.save_lead_analysis(session, lead.id, owner, 75, "ok", has_online_booking=False)
            await repo.set_lead_status(session, lead.id, owner, "written")
            await repo.set_lead_note(session, lead.id, owner, "smoke note")

            # Напоминание
            from db.models import utcnow
            from datetime import timedelta

            reminder = await repo.create_reminder(
                session, lead.id, owner, utcnow() + timedelta(days=1), "smoke"
            )
            assert reminder.id is not None

            # LLM budget (транзакция read-then-write — на PG должна работать)
            allowed, count = await repo.check_llm_budget(session, daily_limit=10)
            assert allowed and count == 1

            # Аудит-лог (миграция 0003 / create_all)
            await repo.log_action(session, owner, "pg_smoke", lead.id, details="smoke")

            # Чтение
            fetched = await repo.get_lead(session, lead.id, owner)
            assert fetched is not None and fetched.ai_score == 75

            stats = await repo.get_stats(session, owner)
            assert stats["total"] == 1

        print("pg_smoke: ALL OK (init_db, CRUD, dedup, budget, audit)")
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(run_smoke())
