"""Phase 6: Chat Sessions, Messages, and Row-Level Security.

Revision ID: 2026_11_13_0003
Revises: 2026_11_13_0002
Create Date: 2026-11-13 21:20:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "2026_11_13_0003"
down_revision: Union[str, None] = "2026_11_13_0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Create chat_sessions table
    op.create_table(
        "chat_sessions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("title", sa.String(length=255), server_default="New Conversation", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_chat_sessions_tenant_id", "chat_sessions", ["tenant_id"])
    op.create_index("ix_chat_sessions_user_id", "chat_sessions", ["user_id"])
    op.create_index("ix_chat_sessions_tenant_user", "chat_sessions", ["tenant_id", "user_id"])
    op.create_index("ix_chat_sessions_tenant_updated", "chat_sessions", ["tenant_id", "updated_at"])

    # 2. Create chat_messages table
    op.create_table(
        "chat_messages",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("session_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("chat_sessions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("role", sa.String(length=32), server_default="user", nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("citations", postgresql.JSON(astext_type=sa.Text()), server_default=sa.text("'[]'::json"), nullable=False),
        sa.Column("message_metadata", postgresql.JSON(astext_type=sa.Text()), server_default=sa.text("'{}'::json"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_chat_messages_session_id", "chat_messages", ["session_id"])
    op.create_index("ix_chat_messages_tenant_id", "chat_messages", ["tenant_id"])
    op.create_index("ix_chat_messages_session_created", "chat_messages", ["session_id", "created_at"])
    op.create_index("ix_chat_messages_tenant_created", "chat_messages", ["tenant_id", "created_at"])

    # 3. Enable and Enforce Row-Level Security on chat_sessions
    op.execute("ALTER TABLE chat_sessions ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE chat_sessions FORCE ROW LEVEL SECURITY")
    op.execute("""
        CREATE POLICY chat_sessions_tenant_isolation_policy ON chat_sessions
        AS PERMISSIVE
        FOR ALL
        USING (tenant_id::text = NULLIF(current_setting('app.current_tenant_id', true), ''))
        WITH CHECK (tenant_id::text = NULLIF(current_setting('app.current_tenant_id', true), ''))
    """)

    # 4. Enable and Enforce Row-Level Security on chat_messages
    op.execute("ALTER TABLE chat_messages ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE chat_messages FORCE ROW LEVEL SECURITY")
    op.execute("""
        CREATE POLICY chat_messages_tenant_isolation_policy ON chat_messages
        AS PERMISSIVE
        FOR ALL
        USING (tenant_id::text = NULLIF(current_setting('app.current_tenant_id', true), ''))
        WITH CHECK (tenant_id::text = NULLIF(current_setting('app.current_tenant_id', true), ''))
    """)


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS chat_messages_tenant_isolation_policy ON chat_messages")
    op.execute("DROP POLICY IF EXISTS chat_sessions_tenant_isolation_policy ON chat_sessions")
    op.drop_table("chat_messages")
    op.drop_table("chat_sessions")
