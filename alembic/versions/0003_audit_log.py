"""0003: Audit log — журнал действий пользователя (AUDIT-1).

Таблица audit_log записывает все значимые действия: смену статуса, удаление,
экспорт, создание напоминаний и т.п. Используется для расследования инцидентов
и анализа воронки действий.

Запись в audit_log — best-effort (repo.log_action): сбой аудита не ломает
основную бизнес-операцию, только логируется.

Run:
    cd /path/to/sales_agent_bot
    source venv/bin/activate
    DB_URL=postgresql+asyncpg://user:pass@host/db alembic upgrade head
    # или для SQLite (таблица создастся автоматически через init_db):
    alembic upgrade head
"""

revision = "0003"
down_revision = "0002"

from alembic import op
import sqlalchemy as sa


def upgrade() -> None:
    op.create_table(
        "audit_log",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("owner_tg_id", sa.BigInteger(), nullable=False, index=True),
        sa.Column("action", sa.String(50), nullable=False, index=True),
        sa.Column("lead_id", sa.Integer(), nullable=True, index=True),
        sa.Column("details", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, index=True),
    )


def downgrade() -> None:
    op.drop_table("audit_log")
