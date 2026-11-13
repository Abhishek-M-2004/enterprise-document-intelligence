"""Neural Cross-Encoder reranking service using BAAI/bge-reranker-base."""

import asyncio
import threading
import time
from typing import Any, Dict, List, Optional
import numpy as np
import torch
from sentence_transformers import CrossEncoder

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)


class RerankerService:
    """Thread-safe singleton service for neural query-passage reranking.
    
    Uses BAAI/bge-reranker-base cross-encoder model to score (query, candidate)
    pairs and produce a refined relevance ordering over retrieved chunks.
    """

    _instance: Optional["RerankerService"] = None
    _lock = threading.Lock()

    def __init__(self) -> None:
        self._model: Optional[Any] = None
        self._model_lock = threading.Lock()
        self._model_loading_ms: float = 0.0
        self._device: Optional[str] = None
        self._is_test_mock: bool = False

    @classmethod
    def get_instance(cls) -> "RerankerService":
        """Return the process-wide cached singleton instance."""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    @classmethod
    def reset_instance_for_testing(cls) -> None:
        """Reset the singleton instance (primarily for isolated test fixtures)."""
        with cls._lock:
            cls._instance = None

    @property
    def is_loaded(self) -> bool:
        """Check whether the cross-encoder model is currently loaded in memory."""
        return self._model is not None

    @property
    def model_loading_ms(self) -> float:
        """Return the time in milliseconds taken to load the model."""
        return self._model_loading_ms

    @property
    def device(self) -> str:
        """Return the device (cuda or cpu) configured/selected for inference."""
        if self._device is None:
            if settings.RERANKER_DEVICE:
                self._device = settings.RERANKER_DEVICE
            else:
                self._device = "cuda" if torch.cuda.is_available() else "cpu"
        return self._device

    def set_model_for_testing(self, mock_model: Any) -> None:
        """Inject a deterministic mock model for fast unit testing."""
        with self._model_lock:
            self._model = mock_model
            self._is_test_mock = True
            self._model_loading_ms = 0.1

    def _get_model(self) -> Any:
        """Lazy-load the CrossEncoder model thread-safely."""
        if self._model is not None:
            return self._model

        with self._model_lock:
            if self._model is not None:
                return self._model

            model_name = settings.RERANKER_MODEL_NAME
            device = self.device
            max_length = settings.RERANKER_MAX_LENGTH

            logger.info(
                f"Loading BGE Cross-Encoder model '{model_name}' on device '{device}' "
                f"(max_length={max_length})..."
            )
            t0 = time.perf_counter()
            try:
                try:
                    self._model = CrossEncoder(
                        model_name=model_name,
                        max_length=max_length,
                        device=device,
                        local_files_only=True,
                    )
                except Exception:
                    self._model = CrossEncoder(
                        model_name=model_name,
                        max_length=max_length,
                        device=device,
                    )
                self._model_loading_ms = round((time.perf_counter() - t0) * 1000, 2)
                logger.info(
                    f"Cross-Encoder '{model_name}' loaded successfully in {self._model_loading_ms} ms."
                )
            except Exception as e:
                logger.error(f"Failed to load Cross-Encoder '{model_name}': {e}")
                raise RuntimeError(
                    f"Could not initialize BGE Cross-Encoder model '{model_name}': {e}"
                ) from e

            return self._model

    def rerank(
        self,
        query: str,
        candidates: List[Dict[str, Any]],
        top_n: int = 10,
    ) -> List[Dict[str, Any]]:
        """Synchronously score (query, candidate) pairs and sort descending by relevance.
        
        Preserves all candidate provenance metadata (chunk_id, document_id, filename,
        page_number, vector_score, bm25_score, rrf_score, retrieval_sources).
        """
        if not candidates:
            return []

        if not query or not query.strip():
            return []

        query_clean = query.strip()
        model = self._get_model()

        # Build (query, passage) pairs
        pairs = []
        for c in candidates:
            content = c.get("content", "")
            pairs.append([query_clean, str(content)])

        # Run cross-encoder inference
        raw_scores = model.predict(
            pairs,
            batch_size=settings.RERANKER_BATCH_SIZE,
            show_progress_bar=False,
        )

        # Handle scalar or 1D array from predict()
        if isinstance(raw_scores, (int, float, np.floating)):
            scores = [float(raw_scores)]
        elif isinstance(raw_scores, np.ndarray):
            scores = raw_scores.astype(float).tolist()
        else:
            scores = [float(s) for s in raw_scores]

        # Attach original rank (1-based), scores, and retain all provenance
        scored_candidates = []
        for idx, (cand, score) in enumerate(zip(candidates, scores)):
            item = dict(cand)
            item["original_rank"] = idx + 1
            item["reranker_score"] = round(float(score), 6)
            # score reflects the active strategy score (reranker relevance score)
            item["score"] = round(float(score), 6)
            scored_candidates.append(item)

        # Sort descending by reranker_score
        scored_candidates.sort(key=lambda x: x["reranker_score"], reverse=True)

        return scored_candidates[:top_n]

    async def rerank_async(
        self,
        query: str,
        candidates: List[Dict[str, Any]],
        top_n: int = 10,
    ) -> List[Dict[str, Any]]:
        """Asynchronously execute reranking in an external worker thread.
        
        Guarantees that compute-heavy cross-encoder inference never blocks
        the FastAPI asynchronous event loop.
        """
        if not candidates or not query or not query.strip():
            return []
        return await asyncio.to_thread(self.rerank, query, candidates, top_n)
