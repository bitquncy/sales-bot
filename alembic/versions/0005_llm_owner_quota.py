"""0005: per-owner LLM accounting."""

from alembic import op
import sqlalchemy as sa

revision = "0005"
down_revision = "0004"


def upgrade() -> None:
    op.add_column("llm_call_log", sa.Column("owner_tg_id", sa.BigInteger(), nullable=True))
    op.add_column("llm_call_log", sa.Column("operation", sa.String(32), nullable=True))
    op.create_index("ix_llm_call_log_owner_tg_id", "llm_call_log", ["owner_tg_id"])


def downgrade() -> None:
    op.drop_index("ix_llm_call_log_owner_tg_id", table_name="llm_call_log")
    op.drop_column("llm_call_log", "operation")
    op.drop_column("llm_call_log", "owner_tg_id")
