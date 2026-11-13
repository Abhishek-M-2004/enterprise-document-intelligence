"""Reciprocal Rank Fusion (RRF) service for combining multi-source retrieval lists."""

from typing import Any, Dict, List, Optional
import uuid

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)


class RRFService:
    """Combines ranked candidate lists using weighted Reciprocal Rank Fusion."""

    @staticmethod
    def fuse_results(
        vector_results: List[Dict[str, Any]],
        bm25_results: List[Dict[str, Any]],
        top_k: int = 10,
        k_constant: Optional[int] = None,
        vector_weight: Optional[float] = None,
        bm25_weight: Optional[float] = None,
    ) -> List[Dict[str, Any]]:
        """Compute Reciprocal Rank Fusion scores across dense and lexical result sets.
        
        Formula:
            RRF(d) = w_vector / (k + rank_vector(d)) + w_bm25 / (k + rank_bm25(d))
        """
        k = k_constant if k_constant is not None else settings.RRF_K_CONSTANT
        w_vector = vector_weight if vector_weight is not None else settings.RRF_VECTOR_WEIGHT
        w_bm25 = bm25_weight if bm25_weight is not None else settings.RRF_BM25_WEIGHT

        if k <= 0:
            raise ValueError(f"RRF k constant must be strictly positive, got {k}")

        fused_map: Dict[uuid.UUID, Dict[str, Any]] = {}

        # 1. Process Vector Search Rankings (1-based ranks)
        for rank, item in enumerate(vector_results, start=1):
            chunk_id = item["chunk_id"]
            if not isinstance(chunk_id, uuid.UUID):
                chunk_id = uuid.UUID(str(chunk_id))

            vector_score = item.get("score")
            rrf_component = w_vector / (k + rank)

            fused_map[chunk_id] = {
                "chunk_id": chunk_id,
                "document_id": item["document_id"],
                "filename": item.get("filename", "document.pdf"),
                "chunk_index": item.get("chunk_index", 0),
                "page_number": item.get("page_number"),
                "content": item.get("content", ""),
                "vector_score": vector_score,
                "bm25_score": None,
                "rrf_score": rrf_component,
                "vector_rank": rank,
                "bm25_rank": None,
                "retrieval_sources": "vector",
                "metadata": item.get("metadata", {}),
            }

        # 2. Process BM25 Search Rankings (1-based ranks)
        for rank, item in enumerate(bm25_results, start=1):
            chunk_id = item["chunk_id"]
            if not isinstance(chunk_id, uuid.UUID):
                chunk_id = uuid.UUID(str(chunk_id))

            bm25_score = item.get("score")
            rrf_component = w_bm25 / (k + rank)

            if chunk_id in fused_map:
                # Chunk was retrieved by both dense and sparse retrieval
                entry = fused_map[chunk_id]
                entry["rrf_score"] += rrf_component
                entry["bm25_score"] = bm25_score
                entry["bm25_rank"] = rank
                entry["retrieval_sources"] = "both"
            else:
                # Chunk was retrieved exclusively by BM25
                fused_map[chunk_id] = {
                    "chunk_id": chunk_id,
                    "document_id": item["document_id"],
                    "filename": item.get("filename", "document.pdf"),
                    "chunk_index": item.get("chunk_index", 0),
                    "page_number": item.get("page_number"),
                    "content": item.get("content", ""),
                    "vector_score": None,
                    "bm25_score": bm25_score,
                    "rrf_score": rrf_component,
                    "vector_rank": None,
                    "bm25_rank": rank,
                    "retrieval_sources": "bm25",
                    "metadata": item.get("metadata", {}),
                }

        # 3. Sort by descending fused RRF score
        fused_list = list(fused_map.values())
        fused_list.sort(key=lambda x: x["rrf_score"], reverse=True)

        logger.debug(
            f"RRF fusion completed: {len(vector_results)} vector candidates, "
            f"{len(bm25_results)} BM25 candidates -> {len(fused_list)} deduplicated chunks."
        )

        return fused_list[:top_k]
