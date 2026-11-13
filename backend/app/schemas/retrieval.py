"""Pydantic schemas for multi-modal document retrieval and hybrid search."""

from enum import Enum
from typing import Any, Dict, List, Optional
import uuid
from pydantic import BaseModel, ConfigDict, Field


class SearchStrategy(str, Enum):
    """Supported retrieval strategies."""
    VECTOR = "vector"
    BM25 = "bm25"
    HYBRID = "hybrid"
    RERANK = "rerank"


class RetrievalRequest(BaseModel):
    """Request payload for search endpoints."""

    model_config = ConfigDict(extra="forbid")

    query: str = Field(
        ...,
        min_length=1,
        max_length=1000,
        description="Search query string",
        examples=["What is the multi-tenant architecture?"],
    )
    top_k: int = Field(
        default=10,
        ge=1,
        le=100,
        description="Number of top candidates to return",
    )
    document_ids: Optional[List[uuid.UUID]] = Field(
        default=None,
        description="Optional list of document UUIDs to restrict search scope",
    )
    rerank: bool = Field(
        default=False,
        description="Whether to apply BGE Cross-Encoder neural reranking to candidates",
    )
    rerank_candidates: Optional[int] = Field(
        default=None,
        ge=1,
        le=100,
        description="Number of preliminary RRF candidates to supply to the reranker (default: 30)",
    )


class RerankRequest(BaseModel):
    """Dedicated request payload for the neural reranking endpoint."""

    model_config = ConfigDict(extra="forbid")

    query: str = Field(
        ...,
        min_length=1,
        max_length=1000,
        description="Search query string",
    )
    top_k: int = Field(
        default=10,
        ge=1,
        le=100,
        description="Number of top reranked chunks to return",
    )
    candidate_top_k: int = Field(
        default=30,
        ge=1,
        le=100,
        description="Number of preliminary RRF candidate chunks to pass to the reranker",
    )
    document_ids: Optional[List[uuid.UUID]] = Field(
        default=None,
        description="Optional list of document UUIDs to restrict search scope",
    )


class RetrievedChunk(BaseModel):
    """Ranked document chunk returned from retrieval engine."""

    model_config = ConfigDict(from_attributes=True)

    chunk_id: uuid.UUID
    document_id: uuid.UUID
    filename: str
    chunk_index: int
    page_number: Optional[int] = None
    content: str
    score: Optional[float] = Field(
        default=None,
        description="Primary relevance score for active strategy",
    )
    vector_score: Optional[float] = None
    bm25_score: Optional[float] = None
    rrf_score: Optional[float] = None
    reranker_score: Optional[float] = Field(
        default=None,
        description="Neural cross-encoder relevance score (BAAI/bge-reranker-base)",
    )
    original_rank: Optional[int] = Field(
        default=None,
        description="Original 1-indexed rank in preliminary candidate set before reranking",
    )
    metadata: Optional[Dict[str, Any]] = Field(
        default_factory=dict,
        description="Provenance and metadata payload",
    )
    retrieval_sources: str = Field(
        ...,
        description="Source identifier: 'vector', 'bm25', or 'both'",
    )


class RetrievalMetrics(BaseModel):
    """Diagnostic latency and candidate statistics for search execution."""

    query_embedding_ms: Optional[float] = None
    vector_search_ms: Optional[float] = None
    bm25_search_ms: Optional[float] = None
    rrf_fusion_ms: Optional[float] = None
    rerank_ms: Optional[float] = Field(
        default=None,
        description="Latency in milliseconds for neural cross-encoder inference",
    )
    model_loading_ms: Optional[float] = Field(
        default=None,
        description="Initial load latency in milliseconds (if model was loaded during this request)",
    )
    total_latency_ms: float
    vector_candidates: int = 0
    bm25_candidates: int = 0
    candidate_count: Optional[int] = Field(
        default=None,
        description="Number of candidates passed to the reranker",
    )
    final_count: int


class SearchResponse(BaseModel):
    """Standardized multi-strategy search response."""

    query: str
    strategy: str
    rerank_enabled: bool = False
    candidate_count: Optional[int] = None
    total_results: int
    results: List[RetrievedChunk]
    metrics: RetrievalMetrics
