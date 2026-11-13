"""Phase 7: RAG Evaluation Datasets, Samples, Runs, Results and Row-Level Security.

Revision ID: 2026_11_13_0004
Revises: 2026_11_13_0003
Create Date: 2026-11-13 22:00:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "2026_11_13_0004"
down_revision: Union[str, None] = "2026_11_13_0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Create evaluation_datasets table
    op.create_table(
        "evaluation_datasets",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("version", sa.String(length=50), server_default="1.0.0", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_evaluation_datasets_tenant_created", "evaluation_datasets", ["tenant_id", "created_at"])
    op.create_index("ix_evaluation_datasets_tenant_id", "evaluation_datasets", ["tenant_id"])

    # 2. Create evaluation_samples table
    op.create_table(
        "evaluation_samples",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("dataset_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("evaluation_datasets.id", ondelete="CASCADE"), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("ground_truth", sa.Text(), nullable=True),
        sa.Column("reference_contexts", postgresql.JSONB(astext_type=sa.Text()), server_default="[]", nullable=False),
        sa.Column("relevant_document_ids", postgresql.JSONB(astext_type=sa.Text()), server_default="[]", nullable=False),
        sa.Column("sample_metadata", postgresql.JSONB(astext_type=sa.Text()), server_default="{}", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_evaluation_samples_dataset_created", "evaluation_samples", ["dataset_id", "created_at"])
    op.create_index("ix_evaluation_samples_tenant_created", "evaluation_samples", ["tenant_id", "created_at"])
    op.create_index("ix_evaluation_samples_dataset_id", "evaluation_samples", ["dataset_id"])
    op.create_index("ix_evaluation_samples_tenant_id", "evaluation_samples", ["tenant_id"])

    # 3. Create evaluation_runs table
    op.create_table(
        "evaluation_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("dataset_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("evaluation_datasets.id", ondelete="CASCADE"), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("retrieval_strategy", sa.String(length=50), server_default="hybrid_rerank", nullable=False),
        sa.Column("evaluation_status", sa.String(length=50), server_default="PENDING", nullable=False),
        sa.Column("total_samples", sa.Integer(), server_default="0", nullable=False),
        sa.Column("completed_samples", sa.Integer(), server_default="0", nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("aggregate_metrics", postgresql.JSONB(astext_type=sa.Text()), server_default="{}", nullable=False),
        sa.Column("configuration", postgresql.JSONB(astext_type=sa.Text()), server_default="{}", nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_evaluation_runs_tenant_dataset", "evaluation_runs", ["tenant_id", "dataset_id"])
    op.create_index("ix_evaluation_runs_tenant_created", "evaluation_runs", ["tenant_id", "created_at"])
    op.create_index("ix_evaluation_runs_tenant_id", "evaluation_runs", ["tenant_id"])
    op.create_index("ix_evaluation_runs_dataset_id", "evaluation_runs", ["dataset_id"])
    op.create_index("ix_evaluation_runs_evaluation_status", "evaluation_runs", ["evaluation_status"])

    # 4. Create evaluation_results table
    op.create_table(
        "evaluation_results",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("run_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("evaluation_runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("sample_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("evaluation_samples.id", ondelete="CASCADE"), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("generated_answer", sa.Text(), server_default="", nullable=False),
        sa.Column("retrieved_contexts", postgresql.JSONB(astext_type=sa.Text()), server_default="[]", nullable=False),
        sa.Column("retrieved_citations", postgresql.JSONB(astext_type=sa.Text()), server_default="[]", nullable=False),
        sa.Column("faithfulness", sa.Float(), nullable=True),
        sa.Column("answer_relevancy", sa.Float(), nullable=True),
        sa.Column("context_precision", sa.Float(), nullable=True),
        sa.Column("context_recall", sa.Float(), nullable=True),
        sa.Column("answer_correctness", sa.Float(), nullable=True),
        sa.Column("latency_ms", sa.Float(), server_default="0.0", nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_evaluation_results_run_sample", "evaluation_results", ["run_id", "sample_id"])
    op.create_index("ix_evaluation_results_tenant_run", "evaluation_results", ["tenant_id", "run_id"])
    op.create_index("ix_evaluation_results_run_id", "evaluation_results", ["run_id"])
    op.create_index("ix_evaluation_results_tenant_id", "evaluation_results", ["tenant_id"])

    # 5. Enable and Enforce Row-Level Security on all 4 tables
    tables = ["evaluation_datasets", "evaluation_samples", "evaluation_runs", "evaluation_results"]
    for table in tables:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(f"""
            CREATE POLICY {table}_tenant_isolation_policy ON {table}
            AS PERMISSIVE
            FOR ALL
            USING (tenant_id::text = NULLIF(current_setting('app.current_tenant_id', true), ''))
            WITH CHECK (tenant_id::text = NULLIF(current_setting('app.current_tenant_id', true), ''))
        """)


def downgrade() -> None:
    tables = ["evaluation_results", "evaluation_runs", "evaluation_samples", "evaluation_datasets"]
    for table in tables:
        op.execute(f"DROP POLICY IF EXISTS {table}_tenant_isolation_policy ON {table}")
        op.drop_table(table)
