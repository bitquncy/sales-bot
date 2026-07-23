"""Async engine, sessionmaker и инициализация схемы БД."""

from sqlalchemy import event, inspect
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from config import settings


class Base(DeclarativeBase):
    pass


def _set_sqlite_pragma(dbapi_conn, _connection_record) -> None:
    """Настраивает каждое новое SQLite-соединение (DB-1, gap-1).

    - foreign_keys=ON: SQLite не применяет FOREIGN KEY без явного PRAGMA на
      каждом соединении. Без этого удаление лида напрямую через SQL оставит
      «висячие» напоминания.
    - journal_mode=WAL: бот и chat_monitor — два процесса, пишущие в один
      SQLite-файл. В rollback-режиме писатель блокирует читателей и любая
      конкурентная запись быстро даёт SQLITE_BUSY. WAL допускает одного
      писателя параллельно с читателями и снижает число конфликтов.
      Для :memory:-БД pragma безвредна (режим остаётся «memory»).
    - synchronous=NORMAL: безопасный для WAL уровень (по документации SQLite
      потеря возможна только при отключении питания, не при падении процесса),
      заметно дешевле FULL на каждом COMMIT.
    - busy_timeout: конкурентный писатель ждёт освобождения блокировки до 5 сек
      вместо мгновенного SQLITE_BUSY.
    """
    cursor = dbapi_conn.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA synchronous=NORMAL")
    cursor.execute("PRAGMA busy_timeout=5000")
    cursor.close()


def _begin_immediate(conn) -> None:
    """Стартует все транзакции как BEGIN IMMEDIATE (gap-4).

    Listener события "begin" ЗАМЕЩАЕТ стандартный BEGIN диалекта. IMMEDIATE
    сразу берёт RESERVED-блокировку записи, поэтому паттерн read-then-write
    (проверка счётчика -> вставка, как в check_llm_budget) корректно
    сериализуется: второй писатель ждёт первого (busy_timeout) и читает уже
    актуальные данные вместо гонки по устаревшему снапшоту (SQLITE_BUSY_SNAPSHOT).
    """
    conn.exec_driver_sql("BEGIN IMMEDIATE")


def create_engine(db_url: str | None = None) -> AsyncEngine:
    url = db_url or settings.db_url
    if url.startswith("sqlite"):
        eng = create_async_engine(url, echo=False)
        # Pragmas и BEGIN IMMEDIATE подключаем только для SQLite
        event.listen(eng.sync_engine, "connect", _set_sqlite_pragma)
        event.listen(eng.sync_engine, "begin", _begin_immediate)
    else:
        # PostgreSQL и др.: пул соединений на промышленную нагрузку
        # (бот + chat_monitor + поллер напоминаний пишут параллельно).
        eng = create_async_engine(url, echo=False, pool_size=5, max_overflow=10)
    return eng


engine: AsyncEngine = create_engine()
session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


def _ensure_lead_columns(conn) -> None:
    """Лёгкая миграция для УЖЕ существующих SQLite-БД.

    create_all создаёт только отсутствующие таблицы, но не добавляет новые
    колонки в существующие. Для личного бота без Alembic этого достаточно:
    досоздаём недостающие колонки в leads через ALTER TABLE ADD COLUMN.

    Список колонок берётся из ORM-модели Lead (а не хардкодом) — иначе очень
    старые схемы (без source/address) падали на dedup-DELETE ниже с
    «no such column: source» (баг, найденный тестом test_init_db_migrates_*).

    Вызывать ТОЛЬКО для SQLite (использует PRAGMA).
    """
    from sqlalchemy import text

    from db.models import Lead

    existing = {row[1] for row in conn.execute(text("PRAGMA table_info(leads)"))}
    if not existing:
        # Таблица только что создана create_all со всеми колонками и индексами.
        return

    for column in Lead.__table__.columns:
        if column.name in existing:
            continue
        ddl_type = column.type.compile(dialect=conn.dialect)
        conn.execute(text(f"ALTER TABLE leads ADD COLUMN {column.name} {ddl_type}"))
        # source участвует в частичном UNIQUE-индексе ниже: все старые лиды —
        # из поиска (OSM), без бэкфилла они выпали бы из дедупликации.
        if column.name == "source":
            conn.execute(text("UPDATE leads SET source = 'osm' WHERE source IS NULL"))

    # P-4: создаём UNIQUE constraint для дедупликации chat-лидов
    # SQLite не поддерживает ALTER TABLE ADD CONSTRAINT, но CREATE UNIQUE INDEX
    # даёт тот же эффект. Если индекс уже существует — игнорируем ошибку.
    try:
        conn.execute(text(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_chat_lead_dedup "
            "ON leads(owner_tg_id, source_chat, chat_user_id, chat_message_id)"
        ))
    except Exception:
        # Если таблица уже имеет дубликаты или индекс — пропускаем
        pass

    # Не выполняем DELETE/дедупликацию при старте. Любая очистка данных должна
    # быть отдельной Alembic-миграцией после backup и ручной проверки.
    try:
        conn.execute(text(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_osm_lead_dedup "
            "ON leads(owner_tg_id, name, COALESCE(address, '')) "
            "WHERE source = 'osm'"
        ))
    except Exception:
        # В старой dev-БД могут быть дубли. Не удаляем их автоматически:
        # оператор должен выполнить миграцию/очистку осознанно.
        pass


async def init_db(target_engine: AsyncEngine | None = None) -> None:
    """Создаёт таблицы, если их нет; для SQLite досоздаёт недостающие колонки.

    Для PostgreSQL достаточно create_all (свежая схема со всеми индексами);
    миграции существующих PG-баз — через Alembic. _ensure_lead_columns
    использует PRAGMA и потому вызывается только для SQLite.
    """
    # Импорт моделей нужен, чтобы они зарегистрировались в metadata.
    from db import models  # noqa: F401

    eng = target_engine or engine
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        if eng.dialect.name == "sqlite":
            await conn.run_sync(_ensure_lead_columns)


async def verify_schema(target_engine: AsyncEngine | None = None) -> None:
    """Fail-fast проверка production-схемы без DDL/DML.

    Production запускается с AUTO_CREATE_SCHEMA=false после `alembic upgrade
    head`. Если обязательных таблиц/колонок нет, бот падает до polling.
    """
    from db import models  # noqa: F401

    eng = target_engine or engine

    def _inspect(sync_conn) -> tuple[set[str], set[str]]:
        inspector = inspect(sync_conn)
        tables = set(inspector.get_table_names())
        lead_columns = (
            {column["name"] for column in inspector.get_columns("leads")}
            if "leads" in tables else set()
        )
        return tables, lead_columns

    async with eng.connect() as conn:
        tables, lead_columns = await conn.run_sync(_inspect)

    required_tables = {
        "users", "leads", "reminders", "llm_call_log",
        "chat_monitor_settings", "chat_message_inbox", "audit_log",
    }
    required_lead_columns = {
        "id", "owner_tg_id", "name", "source", "status", "deleted_at",
    }
    missing_tables = required_tables - tables
    missing_columns = required_lead_columns - lead_columns
    if missing_tables or missing_columns:
        raise RuntimeError(
            "Database schema is not ready. Run `alembic upgrade head`. "
            f"Missing tables={sorted(missing_tables)}, "
            f"missing leads columns={sorted(missing_columns)}"
        )
