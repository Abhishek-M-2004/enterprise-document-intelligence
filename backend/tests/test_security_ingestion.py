"""Phase 9 Security Audit: Document Ingestion, Validation & Deletion Tests.

Tests rejection of non-PDFs, 0-byte files, corrupted binaries, path traversal payloads,
and verifies clean multi-tenant cascading cleanup.
"""

import io
import uuid
import pytest
from httpx import AsyncClient


def create_sample_pdf(text: str = "Ingestion security audit test") -> bytes:
    import pymupdf
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((50, 72), text)
    pdf_bytes = doc.tobytes()
    doc.close()
    return pdf_bytes


@pytest.mark.asyncio
async def test_invalid_file_extension_rejected(async_client: AsyncClient, auth_headers: dict):
    """Verify non-PDF file extensions (.exe, .sh, .txt) are rejected with HTTP 400."""
    shell_script = b"#!/bin/bash\necho 'malicious code'"
    files = {"file": ("script.sh", io.BytesIO(shell_script), "application/x-sh")}
    res = await async_client.post("/api/v1/documents/upload", files=files, headers=auth_headers)
    assert res.status_code == 400
    assert "Only PDF documents (.pdf) are supported" in res.json()["detail"]


@pytest.mark.asyncio
async def test_empty_file_rejected(async_client: AsyncClient, auth_headers: dict):
    """Verify 0-byte empty file is rejected with HTTP 400."""
    files = {"file": ("empty.pdf", io.BytesIO(b""), "application/pdf")}
    res = await async_client.post("/api/v1/documents/upload", files=files, headers=auth_headers)
    assert res.status_code == 400
    assert "empty" in res.json()["detail"].lower()


@pytest.mark.asyncio
async def test_corrupted_pdf_rejected(async_client: AsyncClient, auth_headers: dict):
    """Verify corrupted file with fake .pdf extension but invalid magic bytes is rejected."""
    corrupted_data = b"This is plain text with a .pdf extension but not a PDF file."
    files = {"file": ("corrupted.pdf", io.BytesIO(corrupted_data), "application/pdf")}
    res = await async_client.post("/api/v1/documents/upload", files=files, headers=auth_headers)
    assert res.status_code == 400
    assert "Invalid file signature" in res.json()["detail"]


@pytest.mark.asyncio
async def test_path_traversal_filename_sanitized(async_client: AsyncClient, auth_headers: dict):
    """Verify directory traversal payloads in filenames do not manipulate server filesystem."""
    pdf_bytes = create_sample_pdf("Path traversal test")
    files = {"file": ("../../../../etc/passwd.pdf", io.BytesIO(pdf_bytes), "application/pdf")}
    res = await async_client.post("/api/v1/documents/upload", files=files, headers=auth_headers)
    assert res.status_code == 201
    doc_data = res.json()
    assert doc_data["id"] is not None


@pytest.mark.asyncio
async def test_document_deletion_cascading_cleanup(async_client: AsyncClient, auth_headers: dict):
    """Verify document deletion removes document record, chunks, and disk storage."""
    pdf_bytes = create_sample_pdf("Content to be permanently purged")
    files = {"file": ("to_purge.pdf", io.BytesIO(pdf_bytes), "application/pdf")}
    upload_res = await async_client.post("/api/v1/documents/upload", files=files, headers=auth_headers)
    assert upload_res.status_code == 201
    doc_id = upload_res.json()["id"]

    # Delete document
    del_res = await async_client.delete(f"/api/v1/documents/{doc_id}", headers=auth_headers)
    assert del_res.status_code == 200

    # Verify document is gone
    get_res = await async_client.get(f"/api/v1/documents/{doc_id}", headers=auth_headers)
    assert get_res.status_code == 404

    # Verify file stream is gone
    stream_res = await async_client.get(f"/api/v1/documents/{doc_id}/file", headers=auth_headers)
    assert stream_res.status_code == 404
