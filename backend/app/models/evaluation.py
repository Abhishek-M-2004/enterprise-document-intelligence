"""SQLAlchemy models for RAG Evaluation and benchmarking with multi-tenant isolation."""

from datetime import datetime, timezone
from enum import Enum
from typing import TYPE_CHECKING, Any, Dict, List, Optional
import uuid
from sqlalchemy import (
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin

if TYPE_CHECKING:
    from app.models.tenant import Tenant


class RetrievalStrategy(str, Enum):
    """Retrieval strategies evaluated in benchmarking experiments."""
    VECTOR_ONLY = "vector"
    BM25_ONLY = "bm25"
    HYBRID_RRF = "hybrid_rrf"
    HYBRID_RERANK = "hybrid_rerank"


class EvaluationStatus(str, Enum):
    """Execution status of an evaluation run."""
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    PARTIALLY_COMPLETED = "PARTIALLY_COMPLETED"


class EvaluationDataset(Base, TimestampMixin):
    """Tenant-isolated collection of benchmark question-answer evaluation samples."""

    __tablename__ = "evaluation_datasets"
    __table_args__ = (
        Index("ix_evaluation_datasets_tenant_created", "tenant_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )
    description: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
    )
    version: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default="1.0.0",
    )

    # Relationships
    samples: Mapped[List["EvaluationSample"]] = relationship(
        "EvaluationSample",
        back_populates="dataset",
        cascade="all, delete-orphan",
        order_by="EvaluationSample.created_at",
    )
    runs: Mapped[List["EvaluationRun"]] = relationship(
        "EvaluationRun",
        back_populates="dataset",
        cascade="all, delete-orphan",
        order_by="EvaluationRun.created_at.desc()",
    )
    tenant: Mapped["Tenant"] = relationship("Tenant")


class EvaluationSample(Base, TimestampMixin):
    """Individual question and ground-truth reference sample within an evaluation dataset."""

    __tablename__ = "evaluation_samples"
    __table_args__ = (
        Index("ix_evaluation_samples_dataset_created", "dataset_id", "created_at"),
        Index("ix_evaluation_samples_tenant_created", "tenant_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    dataset_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("evaluation_datasets.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    question: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )
    ground_truth: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
    )
    reference_contexts: Mapped[List[str]] = mapped_column(
        JSON,
        nullable=False,
        default=list,
    )
    relevant_document_ids: Mapped[List[str]] = mapped_column(
        JSON,
        nullable=False,
        default=list,
    )
    sample_metadata: Mapped[Dict[str, Any]] = mapped_column(
        JSON,
        nullable=False,
        default=dict,
    )

    # Relationships
    dataset: Mapped["EvaluationDataset"] = relationship(
        "EvaluationDataset",
        back_populates="samples",
    )
    results: Mapped[List["EvaluationResult"]] = relationship(
        "EvaluationResult",
        back_populates="sample",
        cascade="all, delete-orphan",
    )
    tenant: Mapped["Tenant"] = relationship("Tenant")


class EvaluationRun(Base):
    """Execution experiment tracking a specific retrieval configuration against a dataset."""

    __tablename__ = "evaluation_runs"
    __table_args__ = (
        Index("ix_evaluation_runs_tenant_dataset", "tenant_id", "dataset_id"),
        Index("ix_evaluation_runs_tenant_created", "tenant_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    dataset_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("evaluation_datasets.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    retrieval_strategy: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default=RetrievalStrategy.HYBRID_RERANK.value,
    )
    evaluation_status: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default=EvaluationStatus.PENDING.value,
        index=True,
    )
    total_samples: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
    )
    completed_samples: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
    )
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    completed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    aggregate_metrics: Mapped[Dict[str, Any]] = mapped_column(
        JSON,
        nullable=False,
        default=dict,
    )
    configuration: Mapped[Dict[str, Any]] = mapped_column(
        JSON,
        nullable=False,
        default=dict,
    )
    error_message: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    # Relationships
    dataset: Mapped["EvaluationDataset"] = relationship(
        "EvaluationDataset",
        back_populates="runs",
    )
    results: Mapped[List["EvaluationResult"]] = relationship(
        "EvaluationResult",
        back_populates="run",
        cascade="all, delete-orphan",
        order_by="EvaluationResult.created_at",
    )
    tenant: Mapped["Tenant"] = relationship("Tenant")


class EvaluationResult(Base):
    """Granular per-sample evaluation metrics produced during an evaluation run."""

    __tablename__ = "evaluation_results"
    __table_args__ = (
        Index("ix_evaluation_results_run_sample", "run_id", "sample_id"),
        Index("ix_evaluation_results_tenant_run", "tenant_id", "run_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("evaluation_runs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    sample_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("evaluation_samples.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    generated_answer: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default="",
    )
    retrieved_contexts: Mapped[List[str]] = mapped_column(
        JSON,
        nullable=False,
        default=list,
    )
    retrieved_citations: Mapped[List[Dict[str, Any]]] = mapped_column(
        JSON,
        nullable=False,
        default=list,
    )
    faithfulness: Mapped[Optional[float]] = mapped_column(
        Float,
        nullable=True,
    )
    answer_relevancy: Mapped[Optional[float]] = mapped_column(
        Float,
        nullable=True,
    )
    context_precision: Mapped[Optional[float]] = mapped_column(
        Float,
        nullable=True,
    )
    context_recall: Mapped[Optional[float]] = mapped_column(
        Float,
        nullable=True,
    )
    answer_correctness: Mapped[Optional[float]] = mapped_column(
        Float,
        nullable=True,
    )
    latency_ms: Mapped[float] = mapped_column(
        Float,
        nullable=False,
        default=0.0,
    )
    error_message: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    # Relationships
    run: Mapped["EvaluationRun"] = relationship(
        "EvaluationRun",
        back_populates="results",
    )
    sample: Mapped["EvaluationSample"] = relationship(
        "EvaluationSample",
        back_populates="results",
    )
    tenant: Mapped["Tenant"] = relationship("Tenant")
