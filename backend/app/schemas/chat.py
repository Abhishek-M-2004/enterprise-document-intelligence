"""Pydantic schemas for Chat Sessions, Messages, Citations, and RAG Q&A endpoints."""

from datetime import datetime
from typing import Any, Dict, List, Optional
import uuid
from pydantic import BaseModel, ConfigDict, Field


class ChatSessionCreate(BaseModel):
    """Payload to create a new chat conversation thread."""
    title: Optional[str] = Field(
        default="New Conversation",
        max_length=255,
        description="Optional title for the conversation thread",
    )


class CitationResponse(BaseModel):
    """Verified source citation grounded in retrieved document passage."""
    source_id: str
    document_id: str
    chunk_id: str
    filename: str
    page_number: Optional[int] = None
    relevant_passage: str
    full_passage: Optional[str] = None
    score: Optional[float] = None
    original_rank: Optional[int] = None
    retrieval_sources: Optional[str] = None
    inferred: Optional[bool] = False


class ChatMessageResponse(BaseModel):
    """Individual message record with citation payload and telemetry."""
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    session_id: uuid.UUID
    role: str
    content: str
    citations: List[CitationResponse] = Field(default_factory=list)
    message_metadata: Dict[str, Any] = Field(default_factory=dict)
    created_at: datetime


class ChatSessionResponse(BaseModel):
    """Summary representation of a chat conversation thread."""
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    tenant_id: uuid.UUID
    user_id: uuid.UUID
    title: str
    created_at: datetime
    updated_at: datetime
    message_count: Optional[int] = 0


class ChatSessionDetailResponse(ChatSessionResponse):
    """Complete conversation thread with chronological message history."""
    messages: List[ChatMessageResponse] = Field(default_factory=list)


class AskQuestionRequest(BaseModel):
    """Payload for one-off stateless RAG question-answering."""
    query: str = Field(
        ...,
        min_length=1,
        max_length=1000,
        description="User question about uploaded enterprise documents",
    )
    document_ids: Optional[List[uuid.UUID]] = Field(
        default=None,
        description="Optional list of document IDs to restrict retrieval scope",
    )
    top_k: int = Field(
        default=5,
        ge=1,
        le=50,
        description="Number of passages to provide to LLM context",
    )
    candidate_top_k: int = Field(
        default=30,
        ge=1,
        le=100,
        description="Number of preliminary candidates retrieved before neural reranking",
    )
    temperature: Optional[float] = Field(
        default=0.1,
        ge=0.0,
        le=1.0,
        description="Sampling temperature",
    )


class SendMessageRequest(BaseModel):
    """Payload to post a new message to an existing conversation thread."""
    content: str = Field(
        ...,
        min_length=1,
        max_length=1000,
        description="User prompt or question",
    )
    document_ids: Optional[List[uuid.UUID]] = Field(
        default=None,
        description="Optional document ID filters",
    )
    top_k: int = Field(
        default=5,
        ge=1,
        le=50,
    )
    candidate_top_k: int = Field(
        default=30,
        ge=1,
        le=100,
    )
    temperature: Optional[float] = Field(
        default=0.1,
        ge=0.0,
        le=1.0,
    )


class RAGResponse(BaseModel):
    """Synchronous answer response with verified citations and diagnostic metrics."""
    answer: str
    citations: List[CitationResponse] = Field(default_factory=list)
    metrics: Dict[str, Any] = Field(default_factory=dict)
    followup_suggestions: List[str] = Field(default_factory=list)
    session_id: Optional[str] = None
