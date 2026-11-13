"""High-level retrieval service orchestrating Vector, BM25, and Hybrid RRF retrieval."""

import time
from typing import Any, Dict, List, Optional
import uuid
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging import get_logger
from app.core.metrics import record_retrieval_latencies
from app.core.qdrant_client import QdrantService
from app.core.tracing import trace_span
from app.repositories.document_repository import DocumentRepository
from app.services.bm25_service import BM25Service
from app.services.embedding_service import EmbeddingService
from app.services.reranker_service import RerankerService
from app.services.rrf_service import RRFService

logger = get_logger(__name__)


class RetrievalService:
    """Coordinates multi-modal document retrieval with strict tenant boundary enforcement."""

    def __init__(self):
        self.embedding_service = EmbeddingService.get_instance()
        self.reranker_service = RerankerService.get_instance()

    async def validate_request(
        self,
        db: AsyncSession,
        tenant_id: uuid.UUID,
        query: str,
        top_k: int,
        document_ids: Optional[List[uuid.UUID]] = None,
    ) -> None:
        """Validate query parameters, top_k limits, and tenant document ownership."""
        if not tenant_id:
            raise ValueError("Authenticated tenant context is strictly required.")

        if not query or not query.strip():
            raise ValueError("Search query cannot be empty or whitespace-only.")

        if len(query.strip()) > settings.MAX_QUERY_LENGTH:
            raise ValueError(
                f"Query length exceeds the maximum permitted limit of {settings.MAX_QUERY_LENGTH} characters."
            )

        if top_k < 1 or top_k > settings.MAX_SEARCH_TOP_K:
            raise ValueError(
                f"top_k must be between 1 and {settings.MAX_SEARCH_TOP_K}, got {top_k}."
            )

        if document_ids:
            is_valid = await DocumentRepository.validate_tenant_documents(
                db=db,
                tenant_id=tenant_id,
                document_ids=document_ids,
            )
            if not is_valid:
                raise ValueError(
                    "One or more specified documents do not belong to this organization or do not exist."
                )

    async def vector_search(
        self,
        db: AsyncSession,
        tenant_id: uuid.UUID,
        query: str,
        top_k: int = 20,
        document_ids: Optional[List[uuid.UUID]] = None,
    ) -> Dict[str, Any]:
        """Perform semantic dense vector retrieval with query embedding and Qdrant filtering."""
        start_total = time.perf_counter()
        await self.validate_request(db, tenant_id, query, top_k, document_ids)

        # 1. Generate query embedding with BGE retrieval prefix
        t0 = time.perf_counter()
        query_vector = self.embedding_service.embed_query(query, apply_instruction=True)
        query_embed_ms = round((time.perf_counter() - t0) * 1000, 2)

        # 2. Query Qdrant with server-enforced tenant filter
        t1 = time.perf_counter()
        raw_results = await QdrantService.search_chunks_async(
            tenant_id=tenant_id,
            query_vector=query_vector,
            top_k=top_k,
            document_ids=document_ids,
        )
        vector_search_ms = round((time.perf_counter() - t1) * 1000, 2)
        total_ms = round((time.perf_counter() - start_total) * 1000, 2)

        formatted_results = []
        for r in raw_results:
            formatted_results.append({
                "chunk_id": r["chunk_id"],
                "document_id": r["document_id"],
                "filename": r.get("filename", "document.pdf"),
                "chunk_index": r.get("chunk_index", 0),
                "page_number": r.get("page_number"),
                "content": r.get("content", ""),
                "score": r.get("score"),
                "vector_score": r.get("score"),
                "bm25_score": None,
                "rrf_score": None,
                "reranker_score": None,
                "original_rank": None,
                "metadata": r.get("metadata", {}),
                "retrieval_sources": "vector",
            })

        logger.info(
            "Vector search completed",
            extra={
                "tenant_id": str(tenant_id),
                "query_preview": query[:40],
                "top_k": top_k,
                "results_count": len(formatted_results),
                "embed_ms": query_embed_ms,
                "search_ms": vector_search_ms,
                "total_ms": total_ms,
            },
        )
        record_retrieval_latencies(vector_s=vector_search_ms / 1000.0)

        return {
            "query": query,
            "strategy": "vector",
            "total_results": len(formatted_results),
            "results": formatted_results,
            "metrics": {
                "query_embedding_ms": query_embed_ms,
                "vector_search_ms": vector_search_ms,
                "bm25_search_ms": None,
                "rrf_fusion_ms": None,
                "total_latency_ms": total_ms,
                "vector_candidates": len(raw_results),
                "bm25_candidates": 0,
                "final_count": len(formatted_results),
            },
        }

    async def bm25_search(
        self,
        db: AsyncSession,
        tenant_id: uuid.UUID,
        query: str,
        top_k: int = 20,
        document_ids: Optional[List[uuid.UUID]] = None,
    ) -> Dict[str, Any]:
        """Perform BM25 lexical search against tenant's persistent lexical index."""
        start_total = time.perf_counter()
        await self.validate_request(db, tenant_id, query, top_k, document_ids)

        # Ensure index exists / synced from DB
        await BM25Service.sync_index_from_db_if_empty(tenant_id, db)

        t0 = time.perf_counter()
        raw_results = BM25Service.search(
            tenant_id=tenant_id,
            query=query,
            top_k=top_k,
            document_ids=document_ids,
        )
        bm25_search_ms = round((time.perf_counter() - t0) * 1000, 2)
        total_ms = round((time.perf_counter() - start_total) * 1000, 2)

        formatted_results = []
        for r in raw_results:
            formatted_results.append({
                "chunk_id": r["chunk_id"],
                "document_id": r["document_id"],
                "filename": r.get("filename", "document.pdf"),
                "chunk_index": r.get("chunk_index", 0),
                "page_number": r.get("page_number"),
                "content": r.get("content", ""),
                "score": r.get("score"),
                "vector_score": None,
                "bm25_score": r.get("score"),
                "rrf_score": None,
                "reranker_score": None,
                "original_rank": None,
                "metadata": r.get("metadata", {}),
                "retrieval_sources": "bm25",
            })

        logger.info(
            "BM25 search completed",
            extra={
                "tenant_id": str(tenant_id),
                "query_preview": query[:40],
                "top_k": top_k,
                "results_count": len(formatted_results),
                "search_ms": bm25_search_ms,
                "total_ms": total_ms,
            },
        )
        record_retrieval_latencies(bm25_s=bm25_search_ms / 1000.0)

        return {
            "query": query,
            "strategy": "bm25",
            "total_results": len(formatted_results),
            "results": formatted_results,
            "metrics": {
                "query_embedding_ms": None,
                "vector_search_ms": None,
                "bm25_search_ms": bm25_search_ms,
                "rrf_fusion_ms": None,
                "total_latency_ms": total_ms,
                "vector_candidates": 0,
                "bm25_candidates": len(raw_results),
                "final_count": len(formatted_results),
            },
        }

    async def hybrid_search(
        self,
        db: AsyncSession,
        tenant_id: uuid.UUID,
        query: str,
        top_k: int = 10,
        document_ids: Optional[List[uuid.UUID]] = None,
        dense_top_k: Optional[int] = None,
        bm25_top_k: Optional[int] = None,
        rerank: bool = False,
        rerank_candidates: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Perform hybrid retrieval combining dense vector search and BM25 via Reciprocal Rank Fusion,
        with optional BGE Cross-Encoder neural reranking.
        """
        start_total = time.perf_counter()
        await self.validate_request(db, tenant_id, query, top_k, document_ids)

        c_dense_k = dense_top_k or settings.DEFAULT_VECTOR_TOP_K
        c_bm25_k = bm25_top_k or settings.DEFAULT_BM25_TOP_K
        candidate_pool_size = (
            rerank_candidates or settings.DEFAULT_RERANK_CANDIDATES
            if rerank
            else top_k
        )

        # 1. Dense Vector Candidate Retrieval
        t_embed_start = time.perf_counter()
        query_vector = self.embedding_service.embed_query(query, apply_instruction=True)
        query_embed_ms = round((time.perf_counter() - t_embed_start) * 1000, 2)

        t_vec_start = time.perf_counter()
        vector_candidates = await QdrantService.search_chunks_async(
            tenant_id=tenant_id,
            query_vector=query_vector,
            top_k=c_dense_k,
            document_ids=document_ids,
        )
        vector_search_ms = round((time.perf_counter() - t_vec_start) * 1000, 2)

        # 2. BM25 Candidate Retrieval
        await BM25Service.sync_index_from_db_if_empty(tenant_id, db)
        t_bm25_start = time.perf_counter()
        bm25_candidates = BM25Service.search(
            tenant_id=tenant_id,
            query=query,
            top_k=c_bm25_k,
            document_ids=document_ids,
        )
        bm25_search_ms = round((time.perf_counter() - t_bm25_start) * 1000, 2)

        # 3. Reciprocal Rank Fusion (fuse up to candidate_pool_size candidates)
        t_rrf_start = time.perf_counter()
        fused_candidates = RRFService.fuse_results(
            vector_results=vector_candidates,
            bm25_results=bm25_candidates,
            top_k=candidate_pool_size,
        )
        rrf_fusion_ms = round((time.perf_counter() - t_rrf_start) * 1000, 2)

        # 4. Optional BGE Cross-Encoder Neural Reranking
        rerank_ms: Optional[float] = None
        model_loading_ms: Optional[float] = None
        raw_final_results: List[Dict[str, Any]] = []

        if rerank:
            t_rerank_start = time.perf_counter()
            raw_final_results = await self.reranker_service.rerank_async(
                query=query,
                candidates=fused_candidates,
                top_n=top_k,
            )
            rerank_ms = round((time.perf_counter() - t_rerank_start) * 1000, 2)
            model_loading_ms = self.reranker_service.model_loading_ms
        else:
            raw_final_results = fused_candidates[:top_k]

        total_ms = round((time.perf_counter() - start_total) * 1000, 2)

        formatted_results = []
        for idx, r in enumerate(raw_final_results):
            score_val = r.get("reranker_score") if rerank else r.get("rrf_score")
            orig_rank = r.get("original_rank") if rerank else None
            formatted_results.append({
                "chunk_id": r["chunk_id"],
                "document_id": r["document_id"],
                "filename": r.get("filename", "document.pdf"),
                "chunk_index": r.get("chunk_index", 0),
                "page_number": r.get("page_number"),
                "content": r.get("content", ""),
                "score": score_val,
                "vector_score": r.get("vector_score"),
                "bm25_score": r.get("bm25_score"),
                "rrf_score": r.get("rrf_score"),
                "reranker_score": r.get("reranker_score"),
                "original_rank": orig_rank,
                "metadata": r.get("metadata", {}),
                "retrieval_sources": r.get("retrieval_sources", "hybrid"),
            })

        logger.info(
            "Hybrid search completed",
            extra={
                "tenant_id": str(tenant_id),
                "query_preview": query[:40],
                "rerank_enabled": rerank,
                "dense_candidates": len(vector_candidates),
                "bm25_candidates": len(bm25_candidates),
                "candidate_pool": len(fused_candidates),
                "final_count": len(formatted_results),
                "rerank_ms": rerank_ms,
                "total_ms": total_ms,
            },
        )
        record_retrieval_latencies(
            vector_s=vector_search_ms / 1000.0,
            bm25_s=bm25_search_ms / 1000.0,
            rerank_s=(rerank_ms / 1000.0 if rerank else None),
        )

        return {
            "query": query,
            "strategy": "hybrid",
            "rerank_enabled": rerank,
            "candidate_count": len(fused_candidates) if rerank else None,
            "total_results": len(formatted_results),
            "results": formatted_results,
            "metrics": {
                "query_embedding_ms": query_embed_ms,
                "vector_search_ms": vector_search_ms,
                "bm25_search_ms": bm25_search_ms,
                "rrf_fusion_ms": rrf_fusion_ms,
                "rerank_ms": rerank_ms,
                "model_loading_ms": model_loading_ms,
                "total_latency_ms": total_ms,
                "vector_candidates": len(vector_candidates),
                "bm25_candidates": len(bm25_candidates),
                "candidate_count": len(fused_candidates) if rerank else None,
                "final_count": len(formatted_results),
            },
        }

    async def hybrid_search_with_reranking(
        self,
        db: AsyncSession,
        tenant_id: uuid.UUID,
        query: str,
        top_k: int = 10,
        candidate_top_k: int = 30,
        document_ids: Optional[List[uuid.UUID]] = None,
        dense_top_k: Optional[int] = None,
        bm25_top_k: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Dedicated neural reranking pipeline: Hybrid RRF candidate generation followed by BGE Cross-Encoder."""
        res = await self.hybrid_search(
            db=db,
            tenant_id=tenant_id,
            query=query,
            top_k=top_k,
            document_ids=document_ids,
            dense_top_k=dense_top_k,
            bm25_top_k=bm25_top_k,
            rerank=True,
            rerank_candidates=candidate_top_k,
        )
        res["strategy"] = "rerank"
        return res
