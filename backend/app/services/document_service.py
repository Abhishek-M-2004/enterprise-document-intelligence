"""Document service orchestrating upload, validation, persistence, and cleanup."""

import io
from typing import List, Optional, Tuple
import uuid
from fastapi import UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging import get_logger
from app.core.metrics import DOCUMENTS_UPLOADED_TOTAL, DOCUMENT_PROCESSING_FAILURES_TOTAL
from app.core.qdrant_client import QdrantService
from app.core.storage import BaseStorageService, get_storage_service
from app.models.document import Document, DocumentChunk, DocumentStatus
from app.repositories.chunk_repository import ChunkRepository
from app.repositories.document_repository import DocumentRepository
from app.services.bm25_service import BM25Service
from app.services.pdf_service import PDFProcessingError, PDFService

logger = get_logger(__name__)


class DocumentServiceError(Exception):
    """Business logic error during document management."""
    pass


class DocumentNotFoundError(DocumentServiceError):
    """Document not found within the specified tenant context."""
    pass


class DocumentService:
    """Orchestrates document operations across storage, database, Celery, and vector DB."""

    def __init__(self, storage: Optional[BaseStorageService] = None):
        self.storage = storage or get_storage_service()

    async def upload_document(
        self,
        db: AsyncSession,
        tenant_id: uuid.UUID,
        user_id: uuid.UUID,
        file: UploadFile,
    ) -> Document:
        """Validate, store, record, and queue a PDF document for asynchronous ingestion."""
        # 1. Validate filename and extension
        original_filename = file.filename or "document.pdf"
        if not original_filename.lower().endswith(".pdf"):
            raise DocumentServiceError("Only PDF documents (.pdf) are supported.")

        # 2. Read file content safely
        try:
            content = await file.read()
        except Exception as e:
            raise DocumentServiceError(f"Failed to read uploaded file: {str(e)}")

        file_size = len(content)
        if file_size == 0:
            raise DocumentServiceError("Uploaded file is empty (0 bytes).")

        if file_size > settings.MAX_UPLOAD_SIZE_BYTES:
            max_mb = settings.MAX_UPLOAD_SIZE_BYTES // (1024 * 1024)
            raise DocumentServiceError(
                f"File size ({round(file_size / (1024 * 1024), 2)} MB) exceeds "
                f"the maximum allowed size of {max_mb} MB."
            )

        # 3. Validate PDF magic bytes
        try:
            PDFService.validate_pdf_bytes(content)
        except PDFProcessingError as pe:
            raise DocumentServiceError(str(pe))

        # 4. Compute SHA-256 Checksum
        checksum = self.storage.compute_checksum(content)

        # 5. Persist to storage
        doc_id = uuid.uuid4()
        try:
            storage_path = self.storage.save_file(
                tenant_id=tenant_id,
                file_id=doc_id,
                content=content,
                extension="pdf",
            )
        except Exception as e:
            logger.error(f"Failed to save file to storage: {e}", exc_info=True)
            raise DocumentServiceError("Failed to persist file to storage.")

        # 6. Create database record with QUEUED status
        document = Document(
            id=doc_id,
            tenant_id=tenant_id,
            uploaded_by=user_id,
            filename=original_filename,
            storage_path=storage_path,
            file_size=file_size,
            mime_type="application/pdf",
            checksum=checksum,
            status=DocumentStatus.QUEUED.value,
            chunk_count=0,
        )
        saved_doc = await DocumentRepository.create(db, document)
        await db.commit()
        await db.refresh(saved_doc)
        DOCUMENTS_UPLOADED_TOTAL.inc()

        # 7. Dispatch Celery asynchronous background task
        try:
            from app.workers.celery_app import process_document
            process_document.delay(str(doc_id), str(tenant_id))
            logger.info(
                f"Queued Celery ingestion task for document {doc_id}",
                extra={"tenant_id": str(tenant_id), "document_id": str(doc_id)},
            )
        except Exception as e:
            # If Celery broker is temporarily unreachable, record warning but do not crash upload
            logger.warning(f"Could not enqueue Celery task immediately ({e}). Status remains QUEUED.")

        return saved_doc

    async def list_documents(
        self,
        db: AsyncSession,
        tenant_id: uuid.UUID,
        page: int = 1,
        page_size: int = 20,
        search: Optional[str] = None,
        status: Optional[str] = None,
    ) -> Tuple[List[Document], int]:
        """List documents strictly isolated by tenant."""
        return await DocumentRepository.list_documents(
            db=db,
            tenant_id=tenant_id,
            page=page,
            page_size=page_size,
            search=search,
            status=status,
        )

    async def get_document(
        self,
        db: AsyncSession,
        tenant_id: uuid.UUID,
        document_id: uuid.UUID,
    ) -> Document:
        """Retrieve document metadata ensuring tenant isolation."""
        doc = await DocumentRepository.get_by_id(db, tenant_id, document_id)
        if not doc:
            raise DocumentNotFoundError("Document not found.")
        return doc

    async def get_document_with_chunks(
        self,
        db: AsyncSession,
        tenant_id: uuid.UUID,
        document_id: uuid.UUID,
    ) -> Document:
        """Retrieve document along with all its relational chunks."""
        doc = await DocumentRepository.get_by_id_with_chunks(db, tenant_id, document_id)
        if not doc:
            raise DocumentNotFoundError("Document not found.")
        return doc

    async def delete_document(
        self,
        db: AsyncSession,
        tenant_id: uuid.UUID,
        document_id: uuid.UUID,
    ) -> bool:
        """Cascading deletion of vectors from Qdrant, file from storage, and DB record."""
        doc = await DocumentRepository.get_by_id(db, tenant_id, document_id)
        if not doc:
            raise DocumentNotFoundError("Document not found.")

        # 1. Update status to DELETING
        await DocumentRepository.update_status(
            db=db,
            document_id=document_id,
            status=DocumentStatus.DELETING.value,
        )

        # 2. Delete vectors from Qdrant
        try:
            await QdrantService.delete_chunks_by_document_async(
                tenant_id=tenant_id,
                document_id=document_id,
            )
        except Exception as qe:
            logger.warning(f"Failed to delete Qdrant vectors for {document_id}: {qe}")

        # 3. Delete file from storage
        try:
            self.storage.delete_file(doc.storage_path)
        except Exception as se:
            logger.warning(f"Failed to delete storage file {doc.storage_path}: {se}")

        # 4. Remove entries from tenant BM25 index
        try:
            BM25Service.remove_document_chunks(tenant_id, document_id)
        except Exception as be:
            logger.warning(f"Failed to remove document from BM25 index: {be}")

        # 5. Delete PostgreSQL record (cascades document_chunks)
        deleted = await DocumentRepository.delete(db, tenant_id, document_id)
        await db.commit()
        logger.info(
            f"Successfully deleted document {document_id} and all associated resources."
        )
        return deleted
