"""0006: atomic Chat Monitor inbox claims."""

from alembic import op
import sqlalchemy as sa

revision = "0006"
down_revision = "0005"


def upgrade() -> None:
    op.create_table(
        "chat_message_inbox",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("owner_tg_id", sa.BigInteger(), nullable=False),
        sa.Column("source_chat", sa.String(500), nullable=False),
        sa.Column("chat_user_id", sa.BigInteger(), nullable=False),
        sa.Column("chat_message_id", sa.BigInteger(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint(
            "owner_tg_id", "source_chat", "chat_user_id", "chat_message_id",
            name="uq_chat_message_inbox",
        ),
    )
    op.create_index("ix_chat_message_inbox_owner_tg_id", "chat_message_inbox", ["owner_tg_id"])
    op.create_index("ix_chat_message_inbox_created_at", "chat_message_inbox", ["created_at"])


def downgrade() -> None:
    op.drop_table("chat_message_inbox")
