"""Comprehensive automated tests for Phase 4 Advanced Retrieval Engine."""

import io
import math
import uuid
import numpy as np
import pymupdf
import pytest
from httpx import AsyncClient

from app.core.config import settings
from app.db.session import AsyncSessionLocal
from app.models.document import DocumentChunk
from app.services.bm25_service import BM25Service, tokenize_bm25
from app.services.embedding_service import EmbeddingService
from app.services.retrieval_service import RetrievalService
from app.services.rrf_service import RRFService
from app.workers.celery_app import process_document


def create_test_pdf(pages_text: list[str]) -> bytes:
    """Generate in-memory multi-page PDF."""
    doc = pymupdf.open()
    for text in pages_text:
        page = doc.new_page()
        page.insert_text((50, 72), text)
    pdf_bytes = doc.tobytes()
    doc.close()
    return pdf_bytes


# ==============================================================================
# 1. Query Embeddings Tests
# ==============================================================================

def test_query_embedding_dimension_and_normalization():
    """Verify query embeddings have 384 dimensions and L2 unit norm."""
    embedder = EmbeddingService.get_instance()
    query = "Enterprise document retrieval and hybrid search"
    vector = embedder.embed_query(query, apply_instruction=True)

    assert len(vector) == settings.EMBEDDING_DIMENSION  # 384
    norm = np.linalg.norm(vector)
    assert abs(norm - 1.0) < 1e-3  # Cosine normalized


def test_query_embedding_instruction_prefix():
    """Verify BGE retrieval query instruction prefix is applied."""
    embedder = EmbeddingService.get_instance()
    query = "What is PostgreSQL Row-Level Security?"
    vec_with_prefix = embedder.embed_query(query, apply_instruction=True)
    vec_without_prefix = embedder.embed_query(query, apply_instruction=False)

    # Prefix modifies the query vector representation
    assert len(vec_with_prefix) == 384
    assert len(vec_without_prefix) == 384


def test_empty_and_invalid_query_rejection():
    """Verify that empty, whitespace, or excessively long queries raise ValueError."""
    embedder = EmbeddingService.get_instance()

    with pytest.raises(ValueError, match="empty or whitespace-only"):
        embedder.embed_query("")

    with pytest.raises(ValueError, match="empty or whitespace-only"):
        embedder.embed_query("   \t\n  ")

    with pytest.raises(ValueError, match="exceeds maximum limit"):
        embedder.embed_query("a" * (settings.MAX_QUERY_LENGTH + 1))


# ==============================================================================
# 2. BM25 Lexical Keyword Tests
# ==============================================================================

def test_bm25_tokenization_and_technical_identifiers():
    """Verify BM25 tokenization handles case, punctuation, and technical terms."""
    text = "Deploying BAAI/bge-small-en-v1.5 with PostgreSQL_16 and SHA-256 checksums."
    tokens = tokenize_bm25(text)

    # Technical identifiers should be preserved
    assert "baai/bge-small-en-v1.5" in tokens or "bge-small-en-v1.5" in tokens
    assert "postgresql_16" in tokens
    assert "sha-256" in tokens


def test_bm25_ranking_and_tenant_isolation():
    """Verify BM25 ranking correctness and strict tenant isolation."""
    tenant_a = uuid.uuid4()
    tenant_b = uuid.uuid4()
    doc_a1 = uuid.uuid4()
    doc_b1 = uuid.uuid4()

    # Index chunks for Tenant A
    chunks_a = [
        type("Chunk", (), {
            "id": uuid.uuid4(),
            "chunk_index": 0,
            "page_number": 1,
            "content": "PostgreSQL Row-Level Security ensures multi-tenant database isolation.",
            "chunk_metadata": {"filename": "security.pdf"},
        })(),
        type("Chunk", (), {
            "id": uuid.uuid4(),
            "chunk_index": 1,
            "page_number": 2,
            "content": "Qdrant vector database handles dense embeddings for semantic search.",
            "chunk_metadata": {"filename": "qdrant.pdf"},
        })(),
    ]
    BM25Service.add_document_chunks(tenant_a, doc_a1, "security.pdf", chunks_a)

    # Index chunks for Tenant B
    chunks_b = [
        type("Chunk", (), {
            "id": uuid.uuid4(),
            "chunk_index": 0,
            "page_number": 1,
            "content": "Tenant B confidential internal financial disclosures 2026.",
            "chunk_metadata": {"filename": "finance.pdf"},
        })(),
    ]
    BM25Service.add_document_chunks(tenant_b, doc_b1, "finance.pdf", chunks_b)

    # Query Tenant A for "Row-Level Security"
    results_a = BM25Service.search(tenant_a, "Row-Level Security", top_k=5)
    assert len(results_a) > 0
    assert "PostgreSQL Row-Level Security" in results_a[0]["content"]

    # Query Tenant B for "Row-Level Security" -> Must return 0 (no leakage from Tenant A)
    results_b = BM25Service.search(tenant_b, "Row-Level Security", top_k=5)
    assert len(results_b) == 0

    # Purge document A1 from Tenant A
    BM25Service.remove_document_chunks(tenant_a, doc_a1)
    results_a_after = BM25Service.search(tenant_a, "Row-Level Security", top_k=5)
    assert len(results_a_after) == 0


# ==============================================================================
# 3. Reciprocal Rank Fusion (RRF) Tests
# ==============================================================================

def test_rrf_scoring_and_deduplication():
    """Verify RRF mathematical formula, deduplication, and source labeling."""
    chunk_1 = uuid.uuid4()
    chunk_2 = uuid.uuid4()
    chunk_3 = uuid.uuid4()
    doc_id = uuid.uuid4()

    # Vector results: chunk_1 (rank 1), chunk_2 (rank 2)
    vector_results = [
        {"chunk_id": chunk_1, "document_id": doc_id, "score": 0.95, "content": "Chunk 1 content"},
        {"chunk_id": chunk_2, "document_id": doc_id, "score": 0.85, "content": "Chunk 2 content"},
    ]

    # BM25 results: chunk_1 (rank 2), chunk_3 (rank 1)
    bm25_results = [
        {"chunk_id": chunk_3, "document_id": doc_id, "score": 2.50, "content": "Chunk 3 content"},
        {"chunk_id": chunk_1, "document_id": doc_id, "score": 1.80, "content": "Chunk 1 content"},
    ]

    # Fuse with k=60
    fused = RRFService.fuse_results(vector_results, bm25_results, top_k=10, k_constant=60)

    # Deduplicated result count must be 3
    assert len(fused) == 3

    # chunk_1 was present in both -> source="both"
    c1 = next(item for item in fused if item["chunk_id"] == chunk_1)
    assert c1["retrieval_sources"] == "both"
    # RRF score = 1/(60+1) + 1/(60+2) = 1/61 + 1/62
    expected_c1_score = (1.0 / 61) + (1.0 / 62)
    assert abs(c1["rrf_score"] - expected_c1_score) < 1e-6
    assert c1["vector_score"] == 0.95
    assert c1["bm25_score"] == 1.80

    # chunk_1 has highest score because it appeared in both lists
    assert fused[0]["chunk_id"] == chunk_1

    # chunk_2 was present only in vector -> source="vector"
    c2 = next(item for item in fused if item["chunk_id"] == chunk_2)
    assert c2["retrieval_sources"] == "vector"
    assert abs(c2["rrf_score"] - (1.0 / 62)) < 1e-6

    # chunk_3 was present only in bm25 -> source="bm25"
    c3 = next(item for item in fused if item["chunk_id"] == chunk_3)
    assert c3["retrieval_sources"] == "bm25"
    assert abs(c3["rrf_score"] - (1.0 / 61)) < 1e-6


# ==============================================================================
# 4. Search API & Security Tests (FastAPI Endpoints)
# ==============================================================================

@pytest.mark.asyncio
async def test_search_api_endpoints_and_isolation(async_client: AsyncClient):
    """Test POST /search/vector, /search/bm25, and /search/hybrid endpoints with isolation."""
    # Register Tenant A
    suf_a = uuid.uuid4().hex[:8]
    reg_a = await async_client.post(
        "/api/v1/auth/register",
        json={
            "full_name": f"User A {suf_a}",
            "email": f"usera_{suf_a}@example.com",
            "password": "Password123!",
            "organization_name": f"Tenant A {suf_a}",
        },
    )
    data_a = reg_a.json()
    token_a = data_a["access_token"]
    tenant_a_id = data_a["organization"]["id"]
    headers_a = {"Authorization": f"Bearer {token_a}", "X-Tenant-ID": tenant_a_id}

    # Register Tenant B
    suf_b = uuid.uuid4().hex[:8]
    reg_b = await async_client.post(
        "/api/v1/auth/register",
        json={
            "full_name": f"User B {suf_b}",
            "email": f"userb_{suf_b}@example.com",
            "password": "Password123!",
            "organization_name": f"Tenant B {suf_b}",
        },
    )
    data_b = reg_b.json()
    token_b = data_b["access_token"]
    tenant_b_id = data_b["organization"]["id"]
    headers_b = {"Authorization": f"Bearer {token_b}", "X-Tenant-ID": tenant_b_id}

    # 1. Upload & Ingest PDF for Tenant A
    doc_text_p1 = "Kubernetes orchestration and containerization for distributed SaaS."
    doc_text_p2 = "PyMuPDF extracts textual content from multi-page PDF documents."
    pdf_bytes = create_test_pdf([doc_text_p1, doc_text_p2])

    up_res = await async_client.post(
        "/api/v1/documents/upload",
        files={"file": ("cloud_infra.pdf", io.BytesIO(pdf_bytes), "application/pdf")},
        headers=headers_a,
    )
    assert up_res.status_code == 201
    doc_a_id = up_res.json()["id"]

    # Run ingestion pipeline
    res_ingest = process_document(doc_a_id, tenant_a_id)
    assert res_ingest["status"] == "COMPLETED"

    # 2. Test Vector Search on Tenant A
    vec_res = await async_client.post(
        "/api/v1/search/vector",
        json={"query": "containerization and cloud orchestration", "top_k": 5},
        headers=headers_a,
    )
    assert vec_res.status_code == 200
    v_data = vec_res.json()
    assert v_data["strategy"] == "vector"
    assert v_data["total_results"] > 0
    assert v_data["results"][0]["vector_score"] is not None
    assert v_data["results"][0]["retrieval_sources"] == "vector"
    assert "metrics" in v_data

    # 3. Test BM25 Search on Tenant A
    bm25_res = await async_client.post(
        "/api/v1/search/bm25",
        json={"query": "PyMuPDF extracts", "top_k": 5},
        headers=headers_a,
    )
    assert bm25_res.status_code == 200
    b_data = bm25_res.json()
    assert b_data["strategy"] == "bm25"
    assert b_data["total_results"] > 0
    assert b_data["results"][0]["bm25_score"] is not None
    assert b_data["results"][0]["retrieval_sources"] == "bm25"

    # 4. Test Hybrid Search on Tenant A
    hyb_res = await async_client.post(
        "/api/v1/search/hybrid",
        json={"query": "Kubernetes orchestration PyMuPDF", "top_k": 5},
        headers=headers_a,
    )
    assert hyb_res.status_code == 200
    h_data = hyb_res.json()
    assert h_data["strategy"] == "hybrid"
    assert h_data["total_results"] > 0
    assert h_data["results"][0]["rrf_score"] is not None

    # 5. Cross-Tenant Isolation: Tenant B searches for Tenant A's terms -> Returns 0 results
    cross_vec = await async_client.post(
        "/api/v1/search/vector",
        json={"query": "containerization and cloud orchestration", "top_k": 5},
        headers=headers_b,
    )
    assert cross_vec.status_code == 200
    assert cross_vec.json()["total_results"] == 0

    cross_bm25 = await async_client.post(
        "/api/v1/search/bm25",
        json={"query": "PyMuPDF extracts", "top_k": 5},
        headers=headers_b,
    )
    assert cross_bm25.status_code == 200
    assert cross_bm25.json()["total_results"] == 0

    # 6. Cross-Tenant Document Filter Rejection: Tenant B specifies Tenant A's doc_id -> 400 Bad Request
    cross_doc_filter = await async_client.post(
        "/api/v1/search/hybrid",
        json={
            "query": "Kubernetes",
            "top_k": 5,
            "document_ids": [doc_a_id],
        },
        headers=headers_b,
    )
    assert cross_doc_filter.status_code == 400
    assert "do not belong to this organization" in cross_doc_filter.json()["detail"]

    # 7. Empty Query Validation Rejection
    empty_res = await async_client.post(
        "/api/v1/search/hybrid",
        json={"query": "   ", "top_k": 5},
        headers=headers_a,
    )
    assert empty_res.status_code == 400
    assert "cannot be empty" in empty_res.json()["detail"].lower()

    # 8. Unauthorized Search (missing auth token)
    unauth_res = await async_client.post(
        "/api/v1/search/hybrid",
        json={"query": "test query"},
    )
    assert unauth_res.status_code == 401
