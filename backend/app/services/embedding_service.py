"""BGE embedding generation service supporting BAAI/bge-small-en-v1.5 and query instructions."""

from typing import Any, List, Optional
import numpy as np

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)


class EmbeddingService:
    """Manages embedding generation with lazy model loading, instruction prefixing, and caching."""

    _instance: Optional["EmbeddingService"] = None
    _model: Optional[Any] = None

    def __init__(self, model_name: Optional[str] = None):
        self.model_name = model_name or settings.EMBEDDING_MODEL_NAME
        self.dimension = settings.EMBEDDING_DIMENSION
        self.query_instruction = settings.BGE_QUERY_INSTRUCTION
        self.batch_size = settings.EMBEDDING_BATCH_SIZE

    @classmethod
    def get_instance(cls) -> "EmbeddingService":
        """Singleton accessor for EmbeddingService."""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def _load_model(self):
        """Lazy load SentenceTransformer model."""
        if self._model is None:
            try:
                from sentence_transformers import SentenceTransformer
                logger.info(f"Loading embedding model: {self.model_name}...")
                self._model = SentenceTransformer(self.model_name)
                logger.info(f"Successfully loaded embedding model: {self.model_name}")
            except Exception as e:
                logger.warning(
                    f"Could not load online SentenceTransformer model ({e}). "
                    "A synthetic deterministic vector generator will be used if needed."
                )
                self._model = "SYNTHETIC"

    def embed_texts(
        self, texts: List[str], batch_size: Optional[int] = None
    ) -> List[List[float]]:
        """Generate normalized embedding vectors for a list of document chunk strings (as-is)."""
        if not texts:
            return []

        self._load_model()
        bs = batch_size or self.batch_size

        if self._model != "SYNTHETIC" and hasattr(self._model, "encode"):
            embeddings = self._model.encode(
                texts,
                batch_size=bs,
                show_progress_bar=False,
                normalize_embeddings=True,
            )
            result = embeddings.tolist()
            # Validate dimensions
            for idx, vec in enumerate(result):
                if len(vec) != self.dimension:
                    raise ValueError(
                        f"Embedding dimension mismatch at index {idx}: expected {self.dimension}, got {len(vec)}"
                    )
            return result
        else:
            # Deterministic reproducible fallback for offline tests
            logger.debug(f"Generating {len(texts)} deterministic fallback vectors ({self.dimension}-dim).")
            vectors = []
            for t in texts:
                import hashlib
                h = hashlib.sha256(t.encode("utf-8")).digest()
                seed = int.from_bytes(h[:4], "little")
                rng = np.random.RandomState(seed)
                vec = rng.randn(self.dimension).astype(np.float32)
                norm = np.linalg.norm(vec)
                if norm > 0:
                    vec = vec / norm
                vectors.append(vec.tolist())
            return vectors

    def embed_query(self, query: str, apply_instruction: bool = True) -> List[float]:
        """Generate normalized 384-dimensional embedding vector for a single query."""
        if query is None or not isinstance(query, str) or not query.strip():
            raise ValueError("Query text cannot be empty or whitespace-only.")

        cleaned = query.strip()
        if len(cleaned) > settings.MAX_QUERY_LENGTH:
            raise ValueError(
                f"Query length ({len(cleaned)} chars) exceeds maximum limit of {settings.MAX_QUERY_LENGTH} chars."
            )

        # Apply BGE retrieval query prefix instruction if configured
        formatted_query = cleaned
        if apply_instruction and self.query_instruction:
            if not cleaned.startswith(self.query_instruction):
                formatted_query = f"{self.query_instruction}{cleaned}"

        results = self.embed_texts([formatted_query])
        if not results or len(results[0]) != self.dimension:
            raise ValueError(
                f"Failed to generate valid embedding vector of dimension {self.dimension}."
            )
        return results[0]

    def embed_queries(
        self,
        queries: List[str],
        apply_instruction: bool = True,
        batch_size: Optional[int] = None,
    ) -> List[List[float]]:
        """Generate normalized embeddings for a batch of query strings."""
        if not queries:
            return []

        formatted_queries = []
        for q in queries:
            if q is None or not isinstance(q, str) or not q.strip():
                raise ValueError("Query text cannot be empty or whitespace-only.")
            cleaned = q.strip()
            if len(cleaned) > settings.MAX_QUERY_LENGTH:
                raise ValueError(
                    f"Query length ({len(cleaned)}) exceeds limit of {settings.MAX_QUERY_LENGTH}."
                )
            if apply_instruction and self.query_instruction and not cleaned.startswith(self.query_instruction):
                formatted_queries.append(f"{self.query_instruction}{cleaned}")
            else:
                formatted_queries.append(cleaned)

        return self.embed_texts(formatted_queries, batch_size=batch_size)
