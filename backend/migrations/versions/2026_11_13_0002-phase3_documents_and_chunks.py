"""Phase 3: Documents, Document Chunks, and Row-Level Security.

Revision ID: 2026_11_13_0002
Revises: 2026_11_13_0001
Create Date: 2026-11-13 19:40:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "2026_11_13_0002"
down_revision: Union[str, None] = "2026_11_13_0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Create Documents Table
    op.create_table(
        "documents",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("uploaded_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("filename", sa.String(length=255), nullable=False),
        sa.Column("storage_path", sa.String(length=500), nullable=False),
        sa.Column("file_size", sa.Integer(), nullable=False),
        sa.Column("mime_type", sa.String(length=100), server_default="application/pdf", nullable=False),
        sa.Column("checksum", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=20), server_default="PENDING", nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("page_count", sa.Integer(), nullable=True),
        sa.Column("chunk_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_documents_tenant_id", "documents", ["tenant_id"])
    op.create_index("ix_documents_uploaded_by", "documents", ["uploaded_by"])
    op.create_index("ix_documents_status", "documents", ["status"])
    op.create_index("ix_documents_tenant_created", "documents", ["tenant_id", "created_at"])
    op.create_index("ix_documents_tenant_status", "documents", ["tenant_id", "status"])

    # 2. Create Document Chunks Table
    op.create_table(
        "document_chunks",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("document_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("documents.id", ondelete="CASCADE"), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("page_number", sa.Integer(), nullable=True),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("token_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("chunk_metadata", postgresql.JSON(astext_type=sa.Text()), server_default=sa.text("'{}'::json"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.UniqueConstraint("document_id", "chunk_index", name="uq_document_chunk_index"),
    )
    op.create_index("ix_document_chunks_document_id", "document_chunks", ["document_id"])
    op.create_index("ix_document_chunks_tenant_id", "document_chunks", ["tenant_id"])
    op.create_index("ix_chunks_tenant_document", "document_chunks", ["tenant_id", "document_id"])

    # 3. Enable and Enforce Row-Level Security on Documents
    op.execute("ALTER TABLE documents ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE documents FORCE ROW LEVEL SECURITY")
    op.execute("""
        CREATE POLICY documents_tenant_isolation_policy ON documents
        AS PERMISSIVE
        FOR ALL
        USING (tenant_id::text = NULLIF(current_setting('app.current_tenant_id', true), ''))
        WITH CHECK (tenant_id::text = NULLIF(current_setting('app.current_tenant_id', true), ''))
    """)

    # 4. Enable and Enforce Row-Level Security on Document Chunks
    op.execute("ALTER TABLE document_chunks ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE document_chunks FORCE ROW LEVEL SECURITY")
    op.execute("""
        CREATE POLICY chunks_tenant_isolation_policy ON document_chunks
        AS PERMISSIVE
        FOR ALL
        USING (tenant_id::text = NULLIF(current_setting('app.current_tenant_id', true), ''))
        WITH CHECK (tenant_id::text = NULLIF(current_setting('app.current_tenant_id', true), ''))
    """)


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS chunks_tenant_isolation_policy ON document_chunks")
    op.execute("DROP POLICY IF EXISTS documents_tenant_isolation_policy ON documents")
    op.drop_table("document_chunks")
    op.drop_table("documents")
