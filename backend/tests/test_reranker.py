"""Comprehensive automated test suite for Phase 5 BGE Cross-Encoder Reranking Engine."""

import io
import uuid
from typing import Any, List
import numpy as np
import pymupdf
import pytest
from httpx import AsyncClient

from app.core.config import settings
from app.db.session import AsyncSessionLocal
from app.services.embedding_service import EmbeddingService
from app.services.reranker_service import RerankerService
from app.services.retrieval_service import RetrievalService
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


class MockCrossEncoder:
    """Deterministic mock cross-encoder model for unit and performance testing."""

    def __init__(self, scores: dict[str, float] = None, default_score: float = 0.5):
        self.scores = scores or {}
        self.default_score = default_score
        self.call_count = 0
        self.last_pairs = []

    def predict(self, pairs: list[list[str]], batch_size: int = 32, show_progress_bar: bool = False):
        self.call_count += 1
        self.last_pairs = pairs
        results = []
        for query, passage in pairs:
            # Score based on passage keyword match or predefined score dict
            matched = False
            for key, val in self.scores.items():
                if key.lower() in passage.lower():
                    results.append(val)
                    matched = True
                    break
            if not matched:
                results.append(self.default_score)
        return np.array(results, dtype=float)


# ==============================================================================
# 1. Model Configuration and Singleton Behavior Tests
# ==============================================================================

def test_reranker_singleton_and_configuration():
    """Verify RerankerService is a process-wide singleton with valid configuration."""
    instance_1 = RerankerService.get_instance()
    instance_2 = RerankerService.get_instance()
    assert instance_1 is instance_2

    assert settings.RERANKER_MODEL_NAME == "BAAI/bge-reranker-base"
    assert settings.RERANKER_BATCH_SIZE == 32
    assert settings.RERANKER_MAX_LENGTH == 512
    assert instance_1.device in ["cpu", "cuda"]


def test_reranker_empty_inputs_do_not_invoke_model():
    """Verify empty queries or empty candidate lists return [] without model call."""
    service = RerankerService.get_instance()
    mock_model = MockCrossEncoder()
    service.set_model_for_testing(mock_model)

    # Empty candidate list
    res_empty_cand = service.rerank("What is Kubernetes?", [], top_n=10)
    assert res_empty_cand == []
    assert mock_model.call_count == 0

    # Empty / whitespace query
    cand = [{"chunk_id": uuid.uuid4(), "content": "Some text"}]
    res_empty_q = service.rerank("   ", cand, top_n=10)
    assert res_empty_q == []
    assert mock_model.call_count == 0


# ==============================================================================
# 2. Score Association, Ordering, and Metadata Preservation
# ==============================================================================

def test_reranking_score_association_and_sorting():
    """Verify candidate reordering by descending cross-encoder score, rank tracking, and metadata preservation."""
    service = RerankerService.get_instance()

    c1_id = uuid.uuid4()
    c2_id = uuid.uuid4()
    c3_id = uuid.uuid4()
    doc_id = uuid.uuid4()

    # Preliminary RRF candidates (c1 ranked 1st, c2 ranked 2nd, c3 ranked 3rd)
    candidates = [
        {
            "chunk_id": c1_id,
            "document_id": doc_id,
            "filename": "infra.pdf",
            "chunk_index": 0,
            "page_number": 1,
            "content": "Low relevance chunk talking about generic server maintenance.",
            "vector_score": 0.88,
            "bm25_score": 1.20,
            "rrf_score": 0.032,
            "retrieval_sources": "both",
            "metadata": {"section": "intro"},
        },
        {
            "chunk_id": c2_id,
            "document_id": doc_id,
            "filename": "infra.pdf",
            "chunk_index": 1,
            "page_number": 2,
            "content": "Medium relevance chunk discussing PostgreSQL connection pools.",
            "vector_score": 0.75,
            "bm25_score": 2.10,
            "rrf_score": 0.030,
            "retrieval_sources": "bm25",
            "metadata": {"section": "db"},
        },
        {
            "chunk_id": c3_id,
            "document_id": doc_id,
            "filename": "infra.pdf",
            "chunk_index": 2,
            "page_number": 3,
            "content": "High relevance passage detailing BGE Cross-Encoder neural reranking with Transformers.",
            "vector_score": 0.65,
            "bm25_score": 0.90,
            "rrf_score": 0.025,
            "retrieval_sources": "vector",
            "metadata": {"section": "reranker"},
        },
    ]

    # Mock CrossEncoder that gives highest score to BGE passage, medium to PostgreSQL, low to generic
    mock_model = MockCrossEncoder(
        scores={
            "BGE Cross-Encoder": 3.85,
            "PostgreSQL": 1.40,
            "generic": -0.60,
        }
    )
    service.set_model_for_testing(mock_model)

    query = "How does BGE neural reranking work?"
    reranked = service.rerank(query, candidates, top_n=3)

    assert len(reranked) == 3
    # c3 should be promoted to #1 rank
    assert reranked[0]["chunk_id"] == c3_id
    assert reranked[0]["original_rank"] == 3  # was rank 3 in RRF
    assert reranked[0]["reranker_score"] == 3.85
    assert reranked[0]["score"] == 3.85
    assert reranked[0]["metadata"]["section"] == "reranker"
    assert reranked[0]["retrieval_sources"] == "vector"

    # c2 should be #2 rank
    assert reranked[1]["chunk_id"] == c2_id
    assert reranked[1]["original_rank"] == 2
    assert reranked[1]["reranker_score"] == 1.40

    # c1 should be demoted to #3 rank
    assert reranked[2]["chunk_id"] == c1_id
    assert reranked[2]["original_rank"] == 1
    assert reranked[2]["reranker_score"] == -0.60
    assert reranked[2]["rrf_score"] == 0.032
    assert reranked[2]["vector_score"] == 0.88


def test_top_n_truncation():
    """Verify top_n truncates output to exactly the specified number of items."""
    service = RerankerService.get_instance()
    mock_model = MockCrossEncoder()
    service.set_model_for_testing(mock_model)

    candidates = [
        {"chunk_id": uuid.uuid4(), "content": f"Chunk passage {i}", "document_id": uuid.uuid4()}
        for i in range(10)
    ]

    reranked = service.rerank("test query", candidates, top_n=4)
    assert len(reranked) == 4


def test_batch_processing_large_candidate_pool():
    """Verify inference runs across candidate pools larger than batch_size without truncation."""
    service = RerankerService.get_instance()
    mock_model = MockCrossEncoder()
    service.set_model_for_testing(mock_model)

    # 45 candidates (> default batch_size of 32)
    candidates = [
        {"chunk_id": uuid.uuid4(), "content": f"Doc candidate content {i}", "document_id": uuid.uuid4()}
        for i in range(45)
    ]

    reranked = service.rerank("batch inference test query", candidates, top_n=45)
    assert len(reranked) == 45
    assert mock_model.call_count == 1
    assert len(mock_model.last_pairs) == 45


# ==============================================================================
# 3. Hybrid Retrieval Integration Tests (RetrievalService)
# ==============================================================================

@pytest.mark.asyncio
async def test_retrieval_service_hybrid_rerank_toggle():
    """Verify hybrid_search toggles reranking transparently based on rerank parameter."""
    service = RetrievalService()

    # Deterministic mock scorer
    mock_model = MockCrossEncoder(
        scores={"PostgreSQL": 2.50, "Kubernetes": 1.20},
        default_score=0.10,
    )
    RerankerService.get_instance().set_model_for_testing(mock_model)

    tenant_id = uuid.uuid4()

    # Test with rerank=False -> returns standard RRF
    # Note: Using mock DB session or empty tenant index
    async with AsyncSessionLocal() as db:
        res_no_rerank = await service.hybrid_search(
            db=db,
            tenant_id=tenant_id,
            query="PostgreSQL architecture",
            top_k=5,
            rerank=False,
        )
        assert res_no_rerank["strategy"] == "hybrid"
        assert res_no_rerank["rerank_enabled"] is False
        assert res_no_rerank["metrics"]["rerank_ms"] is None

        # Test with rerank=True
        res_with_rerank = await service.hybrid_search(
            db=db,
            tenant_id=tenant_id,
            query="PostgreSQL architecture",
            top_k=5,
            rerank=True,
            rerank_candidates=15,
        )
        assert res_with_rerank["strategy"] == "hybrid"
        assert res_with_rerank["rerank_enabled"] is True


# ==============================================================================
# 4. Search API Endpoints & Security Isolation Tests
# ==============================================================================

@pytest.mark.asyncio
async def test_rerank_api_and_multi_tenant_isolation(async_client: AsyncClient):
    """Verify /api/v1/search/rerank and /api/v1/search/hybrid?rerank=true with strict isolation."""
    # Ensure deterministic model is active
    mock_model = MockCrossEncoder(
        scores={
            "orchestration": 4.12,
            "PyMuPDF": 2.85,
        },
        default_score=0.20,
    )
    RerankerService.get_instance().set_model_for_testing(mock_model)

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
    doc_text_p1 = "Kubernetes cloud orchestration and microservices containerization architecture."
    doc_text_p2 = "PyMuPDF document text extraction pipeline for enterprise ingestion."
    pdf_bytes = create_test_pdf([doc_text_p1, doc_text_p2])

    up_res = await async_client.post(
        "/api/v1/documents/upload",
        files={"file": ("infra_guide.pdf", io.BytesIO(pdf_bytes), "application/pdf")},
        headers=headers_a,
    )
    assert up_res.status_code == 201
    doc_a_id = up_res.json()["id"]

    res_ingest = process_document(doc_a_id, tenant_a_id)
    assert res_ingest["status"] == "COMPLETED"

    # 2. Test Dedicated /search/rerank endpoint for Tenant A
    rerank_res = await async_client.post(
        "/api/v1/search/rerank",
        json={
            "query": "Kubernetes orchestration PyMuPDF",
            "top_k": 5,
            "candidate_top_k": 20,
        },
        headers=headers_a,
    )
    assert rerank_res.status_code == 200
    r_data = rerank_res.json()
    assert r_data["strategy"] == "rerank"
    assert r_data["rerank_enabled"] is True
    assert r_data["total_results"] > 0
    top_chunk = r_data["results"][0]
    assert top_chunk["reranker_score"] is not None
    assert top_chunk["original_rank"] is not None
    assert "metrics" in r_data
    assert r_data["metrics"]["rerank_ms"] is not None

    # 3. Test /search/hybrid with rerank=True parameter for Tenant A
    hybrid_rerank_res = await async_client.post(
        "/api/v1/search/hybrid",
        json={
            "query": "Kubernetes orchestration PyMuPDF",
            "top_k": 5,
            "rerank": True,
            "rerank_candidates": 20,
        },
        headers=headers_a,
    )
    assert hybrid_rerank_res.status_code == 200
    hr_data = hybrid_rerank_res.json()
    assert hr_data["strategy"] == "hybrid"
    assert hr_data["rerank_enabled"] is True
    assert hr_data["candidate_count"] > 0
    assert hr_data["results"][0]["reranker_score"] is not None

    # 4. Multi-Tenant Isolation: Tenant B searches for Tenant A's terms -> returns 0 results
    cross_rerank = await async_client.post(
        "/api/v1/search/rerank",
        json={
            "query": "Kubernetes orchestration PyMuPDF",
            "top_k": 5,
        },
        headers=headers_b,
    )
    assert cross_rerank.status_code == 200
    assert cross_rerank.json()["total_results"] == 0

    # 5. Security: Cross-Tenant Document Filter Rejection
    cross_filter_res = await async_client.post(
        "/api/v1/search/rerank",
        json={
            "query": "Kubernetes",
            "top_k": 5,
            "document_ids": [doc_a_id],  # Document belongs to Tenant A
        },
        headers=headers_b,  # Tenant B requesting
    )
    assert cross_filter_res.status_code == 400
    assert "do not belong to this organization" in cross_filter_res.json()["detail"]

    # 6. Unauthorized access rejection
    unauth_res = await async_client.post(
        "/api/v1/search/rerank",
        json={"query": "test query"},
    )
    assert unauth_res.status_code == 401

    # 7. Empty query validation
    empty_res = await async_client.post(
        "/api/v1/search/rerank",
        json={"query": "   "},
        headers=headers_a,
    )
    assert empty_res.status_code == 400


# ==============================================================================
# 5. Real BGE Reranker Model Integration Test
# ==============================================================================

def test_real_bge_reranker_model_inference():
    """Integration test verifying real BAAI/bge-reranker-base model inference on CPU."""
    # Reset mock model so real BGE Cross-Encoder is loaded from local cache
    RerankerService.reset_instance_for_testing()
    service = RerankerService.get_instance()

    query = "What is PostgreSQL Row-Level Security?"
    candidates = [
        {
            "chunk_id": uuid.uuid4(),
            "document_id": uuid.uuid4(),
            "filename": "security.pdf",
            "content": "PostgreSQL Row-Level Security restricts rows returned by queries based on current user context.",
        },
        {
            "chunk_id": uuid.uuid4(),
            "document_id": uuid.uuid4(),
            "filename": "cooking.pdf",
            "content": "A classic French onion soup recipe with caramelized onions and gruyere cheese.",
        },
    ]

    reranked = service.rerank(query, candidates, top_n=2)
    assert len(reranked) == 2
    # The PostgreSQL security chunk must be ranked #1 with higher relevance score than cooking
    assert "Row-Level Security" in reranked[0]["content"]
    assert reranked[0]["reranker_score"] > reranked[1]["reranker_score"]
    assert reranked[0]["original_rank"] == 1
    assert reranked[1]["original_rank"] == 2
