"""Chunk repository managing database operations for extracted text chunks."""

from typing import List
from uuid import UUID
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.document import DocumentChunk


class ChunkRepository:
    """Encapsulates data access for DocumentChunk relational metadata."""

    @staticmethod
    async def bulk_create(
        db: AsyncSession, chunks: List[DocumentChunk]
    ) -> List[DocumentChunk]:
        """Bulk insert document chunks into PostgreSQL."""
        if not chunks:
            return []
        db.add_all(chunks)
        await db.flush()
        return chunks

    @staticmethod
    async def get_by_document(
        db: AsyncSession, tenant_id: UUID, document_id: UUID
    ) -> List[DocumentChunk]:
        """Retrieve all chunks belonging to a document ordered by chunk_index."""
        stmt = (
            select(DocumentChunk)
            .where(
                DocumentChunk.document_id == document_id,
                DocumentChunk.tenant_id == tenant_id,
            )
            .order_by(DocumentChunk.chunk_index.asc())
        )
        result = await db.execute(stmt)
        return list(result.scalars().all())

    @staticmethod
    async def delete_by_document(
        db: AsyncSession, tenant_id: UUID, document_id: UUID
    ) -> int:
        """Explicitly delete all chunks associated with a document within a tenant."""
        stmt = delete(DocumentChunk).where(
            DocumentChunk.document_id == document_id,
            DocumentChunk.tenant_id == tenant_id,
        )
        result = await db.execute(stmt)
        await db.flush()
        return result.rowcount
