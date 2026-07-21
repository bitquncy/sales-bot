"""0002: UNIQUE-индекс дедупликации OSM-лидов (owner_tg_id, name, address).

Проблема (gap-2): дедупликация OSM-лидов существовала только на уровне кода
(find_lead_by_name_address -> create_lead), поэтому конкурентная вставка из
двух процессов (бот / chat_monitor / повторный клик) создавала дубли.

Миграция безопасна для существующих БД:
1. Удаляет текущие дубли OSM-лидов, оставляя самый ранний по id. Дубли среди
   soft-deleted тоже чистятся (индекс намеренно включает deleted_at-строки —
   консистентно с кодовой дедупликацией find_lead_by_name_address).
   GROUP BY собирает NULL-адреса в одну группу, поэтому дубли с пустым
   адресом тоже удаляются.
2. Создаёт частичный UNIQUE-индекс только для source='osm'. Chat-лиды не
   ограничиваются: один пользователь одного чата может порождать несколько
   лидов (одинаковые name/address, разные chat_message_id — их дедуплицирует
   uq_chat_lead_dedup). COALESCE(address, '') нормализует NULL-ы, которые
   SQLite иначе считает различными в уникальных индексах.

Для SQLite DDL индекса вызывается напрямую (IF NOT EXISTS — идемпотентно),
batch-режим не нужен: таблицы не пересоздаются.

Run:
    cd /path/to/sales_agent_bot
    source venv/bin/activate
    DB_URL=sqlite+aiosqlite:///./sales_agent.db alembic upgrade head
"""

revision = "0002"
down_revision = "0001"

from alembic import op
import sqlalchemy as sa


def upgrade() -> None:
    # 1) Чистим существующие дубли OSM-лидов (оставляем MIN(id) в каждой группе).
    op.execute(sa.text(
        "DELETE FROM leads WHERE source = 'osm' AND id NOT IN ("
        "SELECT MIN(id) FROM leads WHERE source = 'osm' "
        "GROUP BY owner_tg_id, name, COALESCE(address, ''))"
    ))

    # 2) Частичный уникальный индекс: гонка конкурентной вставки теперь
    # завершается IntegrityError, а не дубликатом.
    op.execute(sa.text(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_osm_lead_dedup "
        "ON leads(owner_tg_id, name, COALESCE(address, '')) "
        "WHERE source = 'osm'"
    ))


def downgrade() -> None:
    op.execute(sa.text("DROP INDEX IF EXISTS uq_osm_lead_dedup"))
