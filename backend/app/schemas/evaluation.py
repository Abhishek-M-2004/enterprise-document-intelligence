"""Pydantic schemas for RAG Evaluation and Benchmarking APIs."""

from datetime import datetime
from typing import Any, Dict, List, Optional
import uuid
from pydantic import BaseModel, ConfigDict, Field

from app.models.evaluation import EvaluationStatus, RetrievalStrategy


class DatasetCreateRequest(BaseModel):
    """Payload to create an evaluation dataset."""
    name: str = Field(..., min_length=1, max_length=255, description="Human-readable benchmark dataset title.")
    description: Optional[str] = Field(None, max_length=1000, description="Optional description of dataset scope.")
    version: str = Field("1.0.0", max_length=50, description="Semantic version string for dataset tracking.")


class DatasetResponse(BaseModel):
    """Metadata response for an evaluation dataset."""
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    tenant_id: uuid.UUID
    name: str
    description: Optional[str]
    version: str
    sample_count: int = 0
    created_at: datetime
    updated_at: datetime


class SampleCreateRequest(BaseModel):
    """Payload to add an individual evaluation sample."""
    question: str = Field(..., min_length=1, description="Evaluation prompt or question.")
    ground_truth: Optional[str] = Field(None, description="Human-verified reference answer.")
    reference_contexts: List[str] = Field(default_factory=list, description="Expected source passages or contexts.")
    relevant_document_ids: List[str] = Field(default_factory=list, description="IDs of documents expected to contain answers.")
    sample_metadata: Dict[str, Any] = Field(default_factory=dict, description="Arbitrary tags or metadata.")


class SampleUpdateRequest(BaseModel):
    """Payload to review and update reference ground-truth data."""
    ground_truth: Optional[str] = None
    reference_contexts: Optional[List[str]] = None
    sample_metadata: Optional[Dict[str, Any]] = None


class SampleResponse(BaseModel):
    """Evaluation sample response model."""
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    dataset_id: uuid.UUID
    tenant_id: uuid.UUID
    question: str
    ground_truth: Optional[str]
    reference_contexts: List[str]
    relevant_document_ids: List[str]
    sample_metadata: Dict[str, Any]
    created_at: datetime
    updated_at: datetime


class SampleImportResponse(BaseModel):
    """Import summary response for CSV and JSON datasets."""
    success_count: int
    error_count: int
    errors: List[str]


class RunCreateRequest(BaseModel):
    """Payload to launch a benchmark evaluation run."""
    dataset_id: uuid.UUID
    retrieval_strategy: str = Field(
        default=RetrievalStrategy.HYBRID_RERANK.value,
        description="One of 'vector', 'bm25', 'hybrid_rrf', 'hybrid_rerank'.",
    )
    top_k: int = Field(default=5, ge=1, le=50, description="Final number of retrieved passages passed to generation.")
    candidate_top_k: int = Field(default=20, ge=1, le=100, description="Candidate pool size for RRF and reranker.")
    async_execution: bool = Field(default=False, description="Whether to dispatch run to Celery worker.")


class RunResponse(BaseModel):
    """Evaluation experiment run response model."""
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    dataset_id: uuid.UUID
    tenant_id: uuid.UUID
    retrieval_strategy: str
    evaluation_status: str
    total_samples: int
    completed_samples: int
    started_at: datetime
    completed_at: Optional[datetime]
    aggregate_metrics: Dict[str, Any]
    configuration: Dict[str, Any]
    error_message: Optional[str]
    created_at: datetime


class ResultResponse(BaseModel):
    """Granular per-sample evaluation metric response model."""
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    run_id: uuid.UUID
    sample_id: uuid.UUID
    tenant_id: uuid.UUID
    generated_answer: str
    retrieved_contexts: List[str]
    faithfulness: Optional[float]
    answer_relevancy: Optional[float]
    context_precision: Optional[float]
    context_recall: Optional[float]
    answer_correctness: Optional[float]
    latency_ms: float
    error_message: Optional[str]
    created_at: datetime


class StrategyComparisonItem(BaseModel):
    """Comparison item for a single retrieval strategy."""
    run_id: str
    retrieval_strategy: str
    status: str
    total_samples: int
    metrics: Dict[str, Any]


class StrategyComparisonResponse(BaseModel):
    """Side-by-side comparison matrix across retrieval strategies."""
    dataset_id: str
    strategies_evaluated: List[str]
    comparison: List[StrategyComparisonItem]
    timestamp: float
