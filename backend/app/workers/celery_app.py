"""Celery application instance and asynchronous task worker configuration."""

from datetime import datetime, timezone
import logging
from typing import Optional
import uuid
from celery import Celery
from qdrant_client.models import PointStruct
from sqlalchemy import select, text

from app.core.config import settings
from app.core.logging import get_logger
from app.core.metrics import DOCUMENT_PROCESSING_FAILURES_TOTAL
from app.core.qdrant_client import QdrantService
from app.core.storage import get_storage_service
from app.db.session import SyncSessionLocal
from app.models.document import Document, DocumentChunk, DocumentStatus
from app.services.bm25_service import BM25Service
from app.services.chunking_service import ChunkingService
from app.services.embedding_service import EmbeddingService
from app.services.pdf_service import PDFService

logger = get_logger(__name__)

celery_app = Celery(
    "enterprise_doc_intelligence_worker",
    broker=settings.CELERY_BROKER_URL,
    backend=settings.CELERY_RESULT_BACKEND,
)

# Celery production configuration
celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_time_limit=3600,  # 1 hour hard limit for long-running document ingestion
    task_soft_time_limit=3300,  # 55 minutes soft limit
    worker_prefetch_multiplier=1,  # Fair distribution for CPU-intensive document processing
    worker_max_tasks_per_child=100,  # Recycle worker processes to prevent memory leaks
)


@celery_app.task(name="app.workers.celery_app.health_ping")
def health_ping() -> str:
    """Lightweight Celery task to verify asynchronous worker queue connectivity."""
    logger.info("Celery health ping executed successfully.")
    return "pong"


@celery_app.task(
    name="app.workers.celery_app.process_document",
    bind=True,
    max_retries=3,
    default_retry_delay=15,
)
def process_document(self, document_id_str: str, tenant_id_str: str) -> dict:
    """Asynchronous worker pipeline for document ingestion.
    
    Extracts text via PyMuPDF, chunks text, computes BGE embeddings,
    persists chunks to PostgreSQL, and upserts vectors to Qdrant.
    """
    doc_uuid = uuid.UUID(document_id_str)
    tenant_uuid = uuid.UUID(tenant_id_str)
    
    logger.info(
        f"Starting document processing task for document {doc_uuid} (tenant {tenant_uuid})",
        extra={"document_id": str(doc_uuid), "tenant_id": str(tenant_uuid)},
    )

    session = SyncSessionLocal()
    try:
        # Enforce PostgreSQL tenant isolation session variable
        session.execute(
            text("SELECT set_config('app.current_tenant_id', :tid, false)"),
            {"tid": str(tenant_uuid)},
        )

        # 1. Fetch document record
        stmt = select(Document).where(
            Document.id == doc_uuid,
            Document.tenant_id == tenant_uuid,
        )
        doc = session.execute(stmt).scalars().first()
        if not doc:
            logger.error(f"Document {doc_uuid} not found for tenant {tenant_uuid}")
            return {"status": "NOT_FOUND", "document_id": document_id_str}

        # 2. Update status to PROCESSING
        doc.status = DocumentStatus.PROCESSING.value
        doc.updated_at = datetime.now(timezone.utc)
        session.commit()

        # 3. Retrieve stored PDF file
        storage_service = get_storage_service()
        file_path = storage_service.get_absolute_path(doc.storage_path)

        # 4. Extract text using PyMuPDF
        logger.info(f"Extracting PDF text for {doc.filename}...")
        extracted_doc = PDFService.extract_text(file_path)
        doc.page_count = extracted_doc.page_count

        # 5. Chunk text
        logger.info(f"Chunking text for {doc.filename}...")
        chunker = ChunkingService()
        text_chunks = chunker.chunk_document(extracted_doc, document_filename=doc.filename)

        if not text_chunks:
            logger.warning(f"No text extracted or document is empty: {doc.filename}")
            doc.status = DocumentStatus.COMPLETED.value
            doc.chunk_count = 0
            doc.processed_at = datetime.now(timezone.utc)
            session.commit()
            return {
                "status": "COMPLETED",
                "document_id": document_id_str,
                "page_count": doc.page_count,
                "chunk_count": 0,
            }

        # 6. Generate BGE embeddings
        logger.info(f"Generating BGE embeddings for {len(text_chunks)} chunks...")
        embedder = EmbeddingService.get_instance()
        chunk_texts = [tc.content for tc in text_chunks]
        embeddings = embedder.embed_texts(chunk_texts)

        # 7. Persist chunks to PostgreSQL
        db_chunks = []
        for tc in text_chunks:
            db_chunk = DocumentChunk(
                id=uuid.uuid4(),
                document_id=doc_uuid,
                tenant_id=tenant_uuid,
                chunk_index=tc.chunk_index,
                page_number=tc.page_number,
                content=tc.content,
                token_count=tc.token_count,
                chunk_metadata=tc.metadata,
            )
            db_chunks.append(db_chunk)
            session.add(db_chunk)

        session.flush()

        # 8. Upsert vectors to Qdrant
        logger.info(f"Upserting {len(db_chunks)} vectors to Qdrant collection...")
        points = []
        for db_chunk, vector in zip(db_chunks, embeddings):
            point = PointStruct(
                id=str(db_chunk.id),
                vector=vector,
                payload={
                    "tenant_id": str(tenant_uuid),
                    "document_id": str(doc_uuid),
                    "chunk_id": str(db_chunk.id),
                    "chunk_index": db_chunk.chunk_index,
                    "page_number": db_chunk.page_number,
                    "content": db_chunk.content,
                    "token_count": db_chunk.token_count,
                    "metadata": db_chunk.chunk_metadata,
                },
            )
            points.append(point)

        QdrantService.upsert_chunks_sync(points)

        # 9. Update tenant BM25 lexical index
        try:
            BM25Service.add_document_chunks(
                tenant_id=tenant_uuid,
                document_id=doc_uuid,
                filename=doc.filename,
                chunks=db_chunks,
            )
        except Exception as bm25_err:
            logger.warning(f"Failed to update BM25 index for {doc_uuid}: {bm25_err}")

        # 10. Update document status to COMPLETED
        doc.status = DocumentStatus.COMPLETED.value
        doc.chunk_count = len(db_chunks)
        doc.error_message = None
        doc.processed_at = datetime.now(timezone.utc)
        doc.updated_at = datetime.now(timezone.utc)
        session.commit()

        logger.info(
            f"Successfully processed document {doc_uuid}: {doc.page_count} pages, {len(db_chunks)} chunks."
        )
        return {
            "status": "COMPLETED",
            "document_id": document_id_str,
            "page_count": doc.page_count,
            "chunk_count": len(db_chunks),
        }

    except Exception as exc:
        session.rollback()
        logger.error(
            f"Error processing document {document_id_str}: {exc}",
            exc_info=True,
        )
        # Record failure in PostgreSQL
        try:
            # Reopen/reuse session for error recording
            session.execute(
                text("SELECT set_config('app.current_tenant_id', :tid, false)"),
                {"tid": str(tenant_uuid)},
            )
            fail_stmt = select(Document).where(
                Document.id == doc_uuid,
                Document.tenant_id == tenant_uuid,
            )
            fail_doc = session.execute(fail_stmt).scalars().first()
            if fail_doc:
                fail_doc.status = DocumentStatus.FAILED.value
                fail_doc.error_message = str(exc)[:1000]
                fail_doc.updated_at = datetime.now(timezone.utc)
                session.commit()
        except Exception as update_err:
            logger.error(f"Failed to record failure status: {update_err}")

        # Retry transient task failures
        if self.request.retries < self.max_retries:
            raise self.retry(exc=exc)
        DOCUMENT_PROCESSING_FAILURES_TOTAL.inc()
        raise exc
    finally:
        session.close()


@celery_app.task(
    name="app.workers.celery_app.run_evaluation_job",
    bind=True,
    max_retries=2,
    default_retry_delay=10,
)
def run_evaluation_job(self, run_id_str: str, tenant_id_str: str) -> dict:
    """Asynchronous background worker task for long-running Ragas evaluation benchmarks."""
    import asyncio
    from app.db.session import AsyncSessionLocal
    from app.services.evaluation_service import EvaluationService

    logger.info(f"Starting Celery evaluation run {run_id_str} for tenant {tenant_id_str}")
    run_uuid = uuid.UUID(run_id_str)
    tenant_uuid = uuid.UUID(tenant_id_str)

    async def _async_exec():
        async with AsyncSessionLocal() as db:
            await db.execute(
                text("SELECT set_config('app.current_tenant_id', :tid, false)"),
                {"tid": str(tenant_uuid)},
            )
            from app.models.evaluation import EvaluationRun
            stmt = select(EvaluationRun).where(
                EvaluationRun.id == run_uuid,
                EvaluationRun.tenant_id == tenant_uuid,
            )
            res = await db.execute(stmt)
            eval_run = res.scalar_one_or_none()
            if not eval_run:
                logger.error(f"Evaluation run {run_uuid} not found")
                return {"status": "NOT_FOUND"}

            service = EvaluationService()
            await service.run_evaluation(
                db=db,
                tenant_id=tenant_uuid,
                dataset_id=eval_run.dataset_id,
                retrieval_strategy=eval_run.retrieval_strategy,
            )
            return {"status": "COMPLETED", "run_id": run_id_str}

    try:
        return asyncio.run(_async_exec())
    except Exception as exc:
        logger.error(f"Async evaluation task {run_id_str} failed: {exc}", exc_info=True)
        if self.request.retries < self.max_retries:
            raise self.retry(exc=exc)
        raise exc
