"""Document repository managing database operations for documents."""

from datetime import datetime, timezone
from typing import List, Optional, Tuple
from uuid import UUID
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.document import Document, DocumentChunk


class DocumentRepository:
    """Encapsulates tenant-isolated database access for Document entities."""

    @staticmethod
    async def get_by_id(
        db: AsyncSession, tenant_id: UUID, document_id: UUID
    ) -> Optional[Document]:
        """Retrieve a document scoped strictly by tenant and document ID."""
        stmt = select(Document).where(
            Document.id == document_id,
            Document.tenant_id == tenant_id,
        )
        result = await db.execute(stmt)
        return result.scalars().first()

    @staticmethod
    async def get_by_id_with_chunks(
        db: AsyncSession, tenant_id: UUID, document_id: UUID
    ) -> Optional[Document]:
        """Retrieve a document with all relational chunks preloaded."""
        stmt = (
            select(Document)
            .options(selectinload(Document.chunks))
            .where(
                Document.id == document_id,
                Document.tenant_id == tenant_id,
            )
        )
        result = await db.execute(stmt)
        return result.scalars().first()

    @staticmethod
    async def get_by_id_global(
        db: AsyncSession, document_id: UUID
    ) -> Optional[Document]:
        """Retrieve document for background worker tasks where tenant_id is verified."""
        stmt = select(Document).where(Document.id == document_id)
        result = await db.execute(stmt)
        return result.scalars().first()

    @staticmethod
    async def get_by_checksum(
        db: AsyncSession, tenant_id: UUID, checksum: str
    ) -> Optional[Document]:
        """Check if an identical document already exists in this tenant."""
        stmt = select(Document).where(
            Document.tenant_id == tenant_id,
            Document.checksum == checksum,
        )
        result = await db.execute(stmt)
        return result.scalars().first()

    @staticmethod
    async def validate_tenant_documents(
        db: AsyncSession, tenant_id: UUID, document_ids: List[UUID]
    ) -> bool:
        """Verify that all specified document IDs belong strictly to the given tenant."""
        if not document_ids:
            return True
        unique_ids = set(document_ids)
        stmt = select(func.count(Document.id)).where(
            Document.tenant_id == tenant_id,
            Document.id.in_(unique_ids),
        )
        res = await db.execute(stmt)
        count = res.scalar_one()
        return count == len(unique_ids)

    @staticmethod
    async def list_documents(
        db: AsyncSession,
        tenant_id: UUID,
        page: int = 1,
        page_size: int = 20,
        search: Optional[str] = None,
        status: Optional[str] = None,
    ) -> Tuple[List[Document], int]:
        """List documents for a tenant with pagination, filtering, and total count."""
        base_query = select(Document).where(Document.tenant_id == tenant_id)

        if search:
            search_pattern = f"%{search.strip().lower()}%"
            base_query = base_query.where(
                func.lower(Document.filename).like(search_pattern)
            )

        if status:
            base_query = base_query.where(Document.status == status.upper())

        # Total count query
        count_stmt = select(func.count()).select_from(base_query.subquery())
        count_res = await db.execute(count_stmt)
        total = count_res.scalar_one()

        # Paginated items query
        offset = (page - 1) * page_size
        items_stmt = (
            base_query.order_by(desc(Document.created_at))
            .offset(offset)
            .limit(page_size)
        )
        result = await db.execute(items_stmt)
        items = list(result.scalars().all())

        return items, total

    @staticmethod
    async def create(db: AsyncSession, document: Document) -> Document:
        """Persist a new document record."""
        db.add(document)
        await db.flush()
        return document

    @staticmethod
    async def update_status(
        db: AsyncSession,
        document_id: UUID,
        status: str,
        page_count: Optional[int] = None,
        chunk_count: Optional[int] = None,
        error_message: Optional[str] = None,
        processed_at: Optional[datetime] = None,
    ) -> Optional[Document]:
        """Update processing status and statistics for a document."""
        stmt = select(Document).where(Document.id == document_id)
        result = await db.execute(stmt)
        doc = result.scalars().first()
        if not doc:
            return None

        doc.status = status
        doc.updated_at = datetime.now(timezone.utc)
        if page_count is not None:
            doc.page_count = page_count
        if chunk_count is not None:
            doc.chunk_count = chunk_count
        if error_message is not None:
            doc.error_message = error_message
        if processed_at is not None:
            doc.processed_at = processed_at

        await db.flush()
        return doc

    @staticmethod
    async def delete(
        db: AsyncSession, tenant_id: UUID, document_id: UUID
    ) -> bool:
        """Delete document record by ID (cascades chunks automatically)."""
        stmt = select(Document).where(
            Document.id == document_id,
            Document.tenant_id == tenant_id,
        )
        result = await db.execute(stmt)
        doc = result.scalars().first()
        if not doc:
            return False

        await db.delete(doc)
        await db.flush()
        return True
