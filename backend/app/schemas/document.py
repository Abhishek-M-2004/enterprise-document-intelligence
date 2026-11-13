"""Pydantic schemas for Document management and Chunk inspection."""

from datetime import datetime
from typing import Any, Dict, List, Optional
import uuid
from pydantic import BaseModel, ConfigDict, Field


class DocumentResponse(BaseModel):
    """Document metadata response."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    tenant_id: uuid.UUID
    uploaded_by: Optional[uuid.UUID] = None
    filename: str
    storage_path: str
    file_size: int
    mime_type: str
    checksum: str
    status: str
    page_count: Optional[int] = None
    chunk_count: int = 0
    error_message: Optional[str] = None
    processed_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime


class DocumentStatusResponse(BaseModel):
    """Polling response for live ingestion progress."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    filename: str
    status: str
    page_count: Optional[int] = None
    chunk_count: int = 0
    error_message: Optional[str] = None
    processed_at: Optional[datetime] = None
    updated_at: datetime


class DocumentChunkResponse(BaseModel):
    """Extracted text chunk with token count and source coordinates."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    document_id: uuid.UUID
    chunk_index: int
    page_number: Optional[int] = None
    content: str
    token_count: int
    chunk_metadata: Dict[str, Any] = Field(default_factory=dict)
    created_at: datetime


class DocumentDetailResponse(DocumentResponse):
    """Detailed document response including relational chunks."""

    chunks: List[DocumentChunkResponse] = []


class DocumentListResponse(BaseModel):
    """Paginated document list response."""

    items: List[DocumentResponse]
    total: int
    page: int
    page_size: int
    total_pages: int
