"""Initial Alembic migration — creates all tables from scratch.

This migration represents the current state of the sales_agent.db database as
of the initial Alembic setup. Run this on a fresh database to get the current
schema, or on an existing one to apply any missing constraints/columns.

Run:
    cd /path/to/sales_agent_bot
    source venv/bin/activate
    DB_URL=sqlite+aiosqlite:///./sales_agent.db alembic upgrade head

Or (auto-detect from .env):
    source venv/bin/activate
    alembic upgrade head

"""

revision = "0001"
down_revision = None

from alembic import op
import sqlalchemy as sa


def upgrade() -> None:
    # Users table
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tg_user_id", sa.BigInteger(), nullable=False, index=True, unique=True),
        sa.Column("username", sa.String(255), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )

    # Leads table
    op.create_table(
        "leads",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("owner_tg_id", sa.BigInteger(), nullable=False, index=True),
        sa.Column("name", sa.String(500), nullable=False),
        sa.Column("address", sa.String(1000), nullable=True),
        sa.Column("phone", sa.String(100), nullable=True),
        sa.Column("website", sa.String(1000), nullable=True),
        sa.Column("socials", sa.Text(), nullable=True),
        sa.Column("source", sa.String(50), nullable=False, server_default="osm", index=True),
        sa.Column("ai_score", sa.Integer(), nullable=True),
        sa.Column("ai_analysis", sa.Text(), nullable=True),
        sa.Column("has_online_booking", sa.Boolean(), nullable=True),
        sa.Column("niche", sa.String(50), nullable=True, index=True),
        sa.Column("source_chat", sa.String(500), nullable=True),
        sa.Column("chat_username", sa.String(255), nullable=True),
        sa.Column("chat_user_id", sa.BigInteger(), nullable=True, index=True),
        sa.Column("chat_message_id", sa.BigInteger(), nullable=True, index=True),
        sa.Column("message_text", sa.Text(), nullable=True),
        sa.Column("message_date", sa.DateTime(), nullable=True),
        sa.Column("relevance_score", sa.Float(), nullable=True),
        sa.Column("status", sa.String(16), nullable=False, server_default="new", index=True),
        sa.Column("note", sa.Text(), nullable=True),
        # Soft-delete support (P-8)
        sa.Column("deleted_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )

    # Unique constraint for chat-lead deduplication (P-4)
    op.create_index(
        "ix_chat_lead_dedup",
        "leads",
        ["owner_tg_id", "source_chat", "chat_user_id", "chat_message_id"],
        unique=False,
    )

    # Reminders table
    op.create_table(
        "reminders",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("lead_id", sa.Integer(), sa.ForeignKey("leads.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("owner_tg_id", sa.BigInteger(), nullable=False, index=True),
        sa.Column("remind_at", sa.DateTime(), nullable=False, index=True),
        sa.Column("text", sa.Text(), nullable=False, server_default=""),
        sa.Column("is_sent", sa.Boolean(), nullable=False, server_default=sa.false(), index=True),
    )

    # LLM call log (P-2)
    op.create_table(
        "llm_call_log",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, index=True),
    )

    # Chat Monitor Settings
    op.create_table(
        "chat_monitor_settings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("owner_tg_id", sa.BigInteger(), nullable=False, index=True, unique=True),
        sa.Column("is_enabled", sa.Boolean(), nullable=False, server_default=sa.true(), index=True),
        sa.Column("chats", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("min_score", sa.Float(), nullable=False, server_default="0.7"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("chat_monitor_settings")
    op.drop_table("llm_call_log")
    op.drop_table("reminders")
    op.drop_index("ix_chat_lead_dedup", "leads")
    op.drop_table("leads")
    op.drop_table("users")