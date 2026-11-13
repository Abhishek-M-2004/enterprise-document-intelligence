"""Automated tests for Phase 3 Document Management and Ingestion Pipeline."""

import io
import math
import uuid
import numpy as np
import pymupdf
import pytest
from httpx import AsyncClient

from app.core.config import settings
from app.core.storage import get_storage_service
from app.db.session import AsyncSessionLocal
from app.models.document import Document, DocumentChunk, DocumentStatus
from app.repositories.document_repository import DocumentRepository
from app.services.chunking_service import ChunkingService
from app.services.embedding_service import EmbeddingService
from app.services.pdf_service import ExtractedDocument, ExtractedPage, PDFService
from app.workers.celery_app import process_document


def create_sample_pdf(text: str = "This is a test document for multi-tenant enterprise intelligence.") -> bytes:
    """Generate a valid in-memory PDF binary."""
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((50, 72), text)
    pdf_bytes = doc.tobytes()
    doc.close()
    return pdf_bytes


@pytest.mark.asyncio
async def test_pdf_upload_success(async_client: AsyncClient):
    """Test successful PDF upload creating record and returning 201 Created."""
    # 1. Register tenant and user
    unique_suffix = uuid.uuid4().hex[:8]
    reg_res = await async_client.post(
        "/api/v1/auth/register",
        json={
            "full_name": f"Doc Owner {unique_suffix}",
            "email": f"docowner_{unique_suffix}@example.com",
            "password": "StrongPassword123!",
            "organization_name": f"Doc Org {unique_suffix}",
        },
    )
    assert reg_res.status_code == 201
    auth_data = reg_res.json()
    token = auth_data["access_token"]
    tenant_id = auth_data["organization"]["id"]

    # 2. Upload valid PDF
    pdf_bytes = create_sample_pdf("Page 1: Multi-tenant isolated document content.")
    files = {"file": ("enterprise_report.pdf", io.BytesIO(pdf_bytes), "application/pdf")}
    headers = {
        "Authorization": f"Bearer {token}",
        "X-Tenant-ID": tenant_id,
    }

    upload_res = await async_client.post(
        "/api/v1/documents/upload",
        files=files,
        headers=headers,
    )
    assert upload_res.status_code == 201
    doc_data = upload_res.json()
    assert doc_data["filename"] == "enterprise_report.pdf"
    assert doc_data["status"] == "QUEUED"
    assert doc_data["mime_type"] == "application/pdf"
    assert doc_data["file_size"] == len(pdf_bytes)
    assert doc_data["tenant_id"] == tenant_id
    assert len(doc_data["checksum"]) == 64

    # 3. Verify file exists in local storage
    storage = get_storage_service()
    stored_bytes = storage.get_file(doc_data["storage_path"])
    assert stored_bytes == pdf_bytes


@pytest.mark.asyncio
async def test_invalid_pdf_rejected(async_client: AsyncClient):
    """Test invalid files (non-pdf, fake pdf, empty file) are rejected."""
    unique_suffix = uuid.uuid4().hex[:8]
    reg_res = await async_client.post(
        "/api/v1/auth/register",
        json={
            "full_name": f"Validator {unique_suffix}",
            "email": f"validator_{unique_suffix}@example.com",
            "password": "StrongPassword123!",
            "organization_name": f"Val Org {unique_suffix}",
        },
    )
    auth_data = reg_res.json()
    headers = {
        "Authorization": f"Bearer {auth_data['access_token']}",
        "X-Tenant-ID": auth_data["organization"]["id"],
    }

    # 1. Non-pdf extension
    res1 = await async_client.post(
        "/api/v1/documents/upload",
        files={"file": ("malicious.exe", io.BytesIO(b"executable data"), "application/octet-stream")},
        headers=headers,
    )
    assert res1.status_code == 400
    assert "Only PDF documents (.pdf) are supported" in res1.json()["detail"]

    # 2. Fake PDF (invalid magic bytes)
    res2 = await async_client.post(
        "/api/v1/documents/upload",
        files={"file": ("fake.pdf", io.BytesIO(b"NOT A REAL PDF FILE HEADER"), "application/pdf")},
        headers=headers,
    )
    assert res2.status_code == 400
    assert "Invalid file signature" in res2.json()["detail"]

    # 3. Empty file (0 bytes)
    res3 = await async_client.post(
        "/api/v1/documents/upload",
        files={"file": ("empty.pdf", io.BytesIO(b""), "application/pdf")},
        headers=headers,
    )
    assert res3.status_code == 400
    assert "empty" in res3.json()["detail"].lower()


@pytest.mark.asyncio
async def test_multi_tenant_document_isolation(async_client: AsyncClient):
    """Ensure Tenant A's documents cannot be accessed or listed by Tenant B."""
    # Tenant A
    suf_a = uuid.uuid4().hex[:8]
    res_a = await async_client.post(
        "/api/v1/auth/register",
        json={
            "full_name": f"Tenant A User {suf_a}",
            "email": f"user_a_{suf_a}@example.com",
            "password": "Password123!",
            "organization_name": f"Org A {suf_a}",
        },
    )
    data_a = res_a.json()
    headers_a = {"Authorization": f"Bearer {data_a['access_token']}", "X-Tenant-ID": data_a["organization"]["id"]}

    # Tenant B
    suf_b = uuid.uuid4().hex[:8]
    res_b = await async_client.post(
        "/api/v1/auth/register",
        json={
            "full_name": f"Tenant B User {suf_b}",
            "email": f"user_b_{suf_b}@example.com",
            "password": "Password123!",
            "organization_name": f"Org B {suf_b}",
        },
    )
    data_b = res_b.json()
    headers_b = {"Authorization": f"Bearer {data_b['access_token']}", "X-Tenant-ID": data_b["organization"]["id"]}

    # Upload document to Tenant A
    pdf_bytes = create_sample_pdf("Confidential Tenant A Financial Audit 2026.")
    up_res = await async_client.post(
        "/api/v1/documents/upload",
        files={"file": ("tenant_a_confidential.pdf", io.BytesIO(pdf_bytes), "application/pdf")},
        headers=headers_a,
    )
    assert up_res.status_code == 201
    doc_id = up_res.json()["id"]

    # Tenant B tries to get Tenant A's document -> 404 NOT FOUND
    cross_get = await async_client.get(
        f"/api/v1/documents/{doc_id}",
        headers=headers_b,
    )
    assert cross_get.status_code == 404

    # Tenant B lists documents -> Tenant A's document must not appear
    list_b = await async_client.get(
        "/api/v1/documents",
        headers=headers_b,
    )
    assert list_b.status_code == 200
    doc_ids_in_b = [d["id"] for d in list_b.json()["items"]]
    assert doc_id not in doc_ids_in_b


@pytest.mark.asyncio
async def test_pdf_extraction_and_chunking():
    """Verify PyMuPDF text extraction and recursive text chunking logic."""
    # 1. Create a 2-page PDF
    doc = pymupdf.open()
    p1 = doc.new_page()
    p1.insert_text((50, 72), "Section 1: Multi-tenant design patterns in cloud systems.")
    p2 = doc.new_page()
    p2.insert_text((50, 72), "Section 2: High throughput asynchronous retrieval pipelines.")
    pdf_bytes = doc.tobytes()
    doc.close()

    # 2. Extract
    extracted = PDFService.extract_text(pdf_bytes)
    assert extracted.page_count == 2
    assert not extracted.is_empty
    assert "Section 1" in extracted.pages[0].text
    assert "Section 2" in extracted.pages[1].text

    # 3. Chunk
    chunker = ChunkingService(chunk_size=100, chunk_overlap=20)
    chunks = chunker.chunk_document(extracted, "test_doc.pdf")
    assert len(chunks) >= 2
    for chunk in chunks:
        assert chunk.token_count > 0
        assert chunk.page_number in [1, 2]
        assert "filename" in chunk.metadata


@pytest.mark.asyncio
async def test_embedding_generation():
    """Verify BGE embedding dimension (384) and L2 cosine normalization."""
    embedder = EmbeddingService.get_instance()
    texts = [
        "Retrieval-Augmented Generation for enterprise document intelligence.",
        "PostgreSQL Row-Level Security ensures tenant isolation.",
    ]
    embeddings = embedder.embed_texts(texts)
    assert len(embeddings) == 2
    for vec in embeddings:
        assert len(vec) == 384
        # Cosine normalized vectors have L2 norm close to 1.0
        norm = np.linalg.norm(vec)
        assert abs(norm - 1.0) < 1e-3


@pytest.mark.asyncio
async def test_celery_pipeline_and_cascading_deletion(async_client: AsyncClient):
    """Test full asynchronous ingestion pipeline via Celery and cascading deletion."""
    # 1. Register organization
    suf = uuid.uuid4().hex[:8]
    reg_res = await async_client.post(
        "/api/v1/auth/register",
        json={
            "full_name": f"Ingestion Admin {suf}",
            "email": f"ingest_admin_{suf}@example.com",
            "password": "StrongPassword123!",
            "organization_name": f"Ingest Org {suf}",
        },
    )
    auth_data = reg_res.json()
    token = auth_data["access_token"]
    tenant_id = auth_data["organization"]["id"]
    headers = {"Authorization": f"Bearer {token}", "X-Tenant-ID": tenant_id}

    # 2. Upload PDF
    pdf_text = "This is a detailed chapter on RAG architecture and Qdrant vector databases."
    pdf_bytes = create_sample_pdf(pdf_text)
    up_res = await async_client.post(
        "/api/v1/documents/upload",
        files={"file": ("rag_manual.pdf", io.BytesIO(pdf_bytes), "application/pdf")},
        headers=headers,
    )
    assert up_res.status_code == 201
    doc_id = up_res.json()["id"]

    # 3. Run Celery ingestion pipeline directly
    result = process_document(doc_id, tenant_id)
    assert result["status"] == "COMPLETED"
    assert result["chunk_count"] > 0

    # 4. Check document status API
    status_res = await async_client.get(
        f"/api/v1/documents/{doc_id}/status",
        headers=headers,
    )
    assert status_res.status_code == 200
    st_data = status_res.json()
    assert st_data["status"] == "COMPLETED"
    assert st_data["chunk_count"] > 0
    assert st_data["page_count"] == 1

    # 5. Check document detail API (relational chunks)
    detail_res = await async_client.get(
        f"/api/v1/documents/{doc_id}/detail",
        headers=headers,
    )
    assert detail_res.status_code == 200
    detail_data = detail_res.json()
    assert len(detail_data["chunks"]) > 0
    assert detail_data["chunks"][0]["document_id"] == doc_id

    # 6. Delete document
    del_res = await async_client.delete(
        f"/api/v1/documents/{doc_id}",
        headers=headers,
    )
    assert del_res.status_code == 200

    # 7. Verify document is gone
    get_after_del = await async_client.get(
        f"/api/v1/documents/{doc_id}",
        headers=headers,
    )
    assert get_after_del.status_code == 404
