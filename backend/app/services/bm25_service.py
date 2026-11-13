"""BM25 keyword retrieval service with tenant-isolated persistent index."""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
import pickle
import re
import threading
from typing import Any, Dict, List, Optional, Set
import math
import uuid
from rank_bm25 import BM25Okapi
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)


class RobustBM25Okapi(BM25Okapi):
    """BM25Okapi with Lucene-standard positive IDF smoothing ln(1 + (N - n + 0.5) / (n + 0.5)).
    
    Guarantees strictly positive non-zero IDF and scores on any document set size.
    """

    def _calc_idf(self, nd):
        idf_sum = 0
        for word, freq in nd.items():
            idf = math.log(1.0 + (self.corpus_size - freq + 0.5) / (freq + 0.5))
            self.idf[word] = idf
            idf_sum += idf
        self.average_idf = idf_sum / len(self.idf) if self.idf else 0.0


def tokenize_bm25(text: str) -> List[str]:
    """Tokenize text preserving technical terms, acronyms, and compound identifiers."""
    if not text:
        return []
    # Tokenize alphanumeric words, compound terms with hyphens, underscores, dots
    raw_tokens = re.findall(r"\b[a-zA-Z0-9_\-\.]+\b", text.lower())
    # Clean leading/trailing dots/hyphens
    tokens = [t.strip(".-") for t in raw_tokens if t.strip(".-")]
    return tokens


@dataclass
class TenantBM25Index:
    """Represents an in-memory and serialized BM25 index for a single tenant."""
    tenant_id: str
    chunks: List[Dict[str, Any]] = field(default_factory=list)
    corpus_tokens: List[List[str]] = field(default_factory=list)
    bm25: Optional[RobustBM25Okapi] = None
    updated_at: float = 0.0

    def rebuild_bm25(self) -> None:
        """Reinitialize BM25Okapi model from corpus tokens."""
        if self.corpus_tokens:
            self.bm25 = RobustBM25Okapi(self.corpus_tokens)
        else:
            self.bm25 = None
        self.updated_at = datetime.now(timezone.utc).timestamp()


class BM25Service:
    """Manages persistent tenant-isolated BM25 indexes with in-memory caching."""

    _cache: Dict[str, TenantBM25Index] = {}
    _lock = threading.RLock()

    @classmethod
    def _get_tenant_index_dir(cls, tenant_id: uuid.UUID) -> Path:
        """Resolve and ensure isolated directory for tenant BM25 index."""
        base_dir = Path(settings.BM25_INDEX_DIR).resolve()
        tenant_dir = (base_dir / str(tenant_id)).resolve()
        if not str(tenant_dir).startswith(str(base_dir)):
            raise ValueError(f"Path traversal detected in BM25 index path: {tenant_id}")
        tenant_dir.mkdir(parents=True, exist_ok=True)
        return tenant_dir

    @classmethod
    def _get_index_file_path(cls, tenant_id: uuid.UUID) -> Path:
        """Return path to persistent pickle index file."""
        return cls._get_tenant_index_dir(tenant_id) / "bm25_index.pkl"

    @classmethod
    def _save_to_disk(cls, tenant_id: uuid.UUID, index: TenantBM25Index) -> None:
        """Persist tenant BM25 index atomically to disk."""
        target_file = cls._get_index_file_path(tenant_id)
        temp_file = target_file.with_suffix(".tmp")
        try:
            data = {
                "version": 1,
                "tenant_id": str(tenant_id),
                "chunks": index.chunks,
                "corpus_tokens": index.corpus_tokens,
                "updated_at": index.updated_at,
            }
            with open(temp_file, "wb") as f:
                pickle.dump(data, f, protocol=pickle.HIGHEST_PROTOCOL)
            temp_file.replace(target_file)
            logger.info(
                f"Persisted BM25 index for tenant {tenant_id}: {len(index.chunks)} chunks."
            )
        except Exception as e:
            logger.error(f"Failed to persist BM25 index for tenant {tenant_id}: {e}")
            if temp_file.exists():
                temp_file.unlink()

    @classmethod
    def _load_from_disk(cls, tenant_id: uuid.UUID) -> Optional[TenantBM25Index]:
        """Load tenant BM25 index from disk if present."""
        target_file = cls._get_index_file_path(tenant_id)
        if not target_file.exists():
            return None
        try:
            with open(target_file, "rb") as f:
                data = pickle.load(f)
            index = TenantBM25Index(
                tenant_id=str(tenant_id),
                chunks=data.get("chunks", []),
                corpus_tokens=data.get("corpus_tokens", []),
                updated_at=data.get("updated_at", 0.0),
            )
            index.rebuild_bm25()
            return index
        except Exception as e:
            logger.warning(f"Could not load BM25 index for tenant {tenant_id} from disk: {e}")
            return None

    @classmethod
    def get_or_load_index(
        cls, tenant_id: uuid.UUID
    ) -> TenantBM25Index:
        """Retrieve tenant index from memory cache or disk, or create a blank one."""
        tid_str = str(tenant_id)
        with cls._lock:
            if tid_str in cls._cache:
                return cls._cache[tid_str]

            index = cls._load_from_disk(tenant_id)
            if index is None:
                index = TenantBM25Index(tenant_id=tid_str)
                index.rebuild_bm25()

            cls._cache[tid_str] = index
            return index

    @classmethod
    def add_document_chunks(
        cls,
        tenant_id: uuid.UUID,
        document_id: uuid.UUID,
        filename: str,
        chunks: List[Any],
    ) -> None:
        """Incrementally add new document chunks to tenant BM25 index."""
        if not chunks:
            return

        tid_str = str(tenant_id)
        doc_id_str = str(document_id)

        with cls._lock:
            index = cls.get_or_load_index(tenant_id)

            # Avoid duplicates if document was already indexed
            filtered_chunks = []
            filtered_tokens = []
            for c, t in zip(index.chunks, index.corpus_tokens):
                if c["document_id"] != doc_id_str:
                    filtered_chunks.append(c)
                    filtered_tokens.append(t)

            index.chunks = filtered_chunks
            index.corpus_tokens = filtered_tokens

            # Append new chunk tokens
            for chk in chunks:
                chunk_id_str = str(chk.id) if hasattr(chk, "id") else str(uuid.uuid4())
                chunk_idx = chk.chunk_index if hasattr(chk, "chunk_index") else 0
                page_num = chk.page_number if hasattr(chk, "page_number") else None
                content = chk.content if hasattr(chk, "content") else str(chk)
                meta = chk.chunk_metadata if hasattr(chk, "chunk_metadata") else (chk.metadata if hasattr(chk, "metadata") else {})

                tokens = tokenize_bm25(content)
                index.chunks.append({
                    "chunk_id": chunk_id_str,
                    "document_id": doc_id_str,
                    "filename": filename,
                    "chunk_index": chunk_idx,
                    "page_number": page_num,
                    "content": content,
                    "metadata": meta,
                })
                index.corpus_tokens.append(tokens)

            index.rebuild_bm25()
            cls._cache[tid_str] = index
            cls._save_to_disk(tenant_id, index)

    @classmethod
    def remove_document_chunks(
        cls,
        tenant_id: uuid.UUID,
        document_id: uuid.UUID,
    ) -> None:
        """Purge all chunks associated with document from tenant BM25 index."""
        tid_str = str(tenant_id)
        doc_id_str = str(document_id)

        with cls._lock:
            index = cls.get_or_load_index(tenant_id)
            filtered_chunks = []
            filtered_tokens = []
            for c, t in zip(index.chunks, index.corpus_tokens):
                if c["document_id"] != doc_id_str:
                    filtered_chunks.append(c)
                    filtered_tokens.append(t)

            index.chunks = filtered_chunks
            index.corpus_tokens = filtered_tokens
            index.rebuild_bm25()
            cls._cache[tid_str] = index
            cls._save_to_disk(tenant_id, index)
            logger.info(
                f"Purged document {document_id} from BM25 index for tenant {tenant_id}."
            )

    @classmethod
    async def sync_index_from_db_if_empty(
        cls,
        tenant_id: uuid.UUID,
        db: AsyncSession,
    ) -> TenantBM25Index:
        """Sync tenant BM25 index from PostgreSQL if empty."""
        index = cls.get_or_load_index(tenant_id)
        if index.chunks:
            return index

        # Query chunks for this tenant from PostgreSQL
        from app.models.document import Document, DocumentChunk
        stmt = (
            select(DocumentChunk, Document.filename)
            .join(Document, Document.id == DocumentChunk.document_id)
            .where(DocumentChunk.tenant_id == tenant_id)
            .order_by(DocumentChunk.document_id, DocumentChunk.chunk_index)
        )
        res = await db.execute(stmt)
        rows = res.all()

        if rows:
            with cls._lock:
                index.chunks = []
                index.corpus_tokens = []
                for chunk_row, filename in rows:
                    tokens = tokenize_bm25(chunk_row.content)
                    index.chunks.append({
                        "chunk_id": str(chunk_row.id),
                        "document_id": str(chunk_row.document_id),
                        "filename": filename,
                        "chunk_index": chunk_row.chunk_index,
                        "page_number": chunk_row.page_number,
                        "content": chunk_row.content,
                        "metadata": chunk_row.chunk_metadata,
                    })
                    index.corpus_tokens.append(tokens)

                index.rebuild_bm25()
                cls._cache[str(tenant_id)] = index
                cls._save_to_disk(tenant_id, index)

        return index

    @classmethod
    def search(
        cls,
        tenant_id: uuid.UUID,
        query: str,
        top_k: int = 20,
        document_ids: Optional[List[uuid.UUID]] = None,
    ) -> List[Dict[str, Any]]:
        """Execute BM25 lexical keyword retrieval strictly scoped to the tenant."""
        if not tenant_id:
            raise ValueError("tenant_id is strictly required for BM25 search.")

        if not query or not query.strip():
            return []

        index = cls.get_or_load_index(tenant_id)
        if not index.bm25 or not index.chunks:
            return []

        query_tokens = tokenize_bm25(query)
        if not query_tokens:
            return []

        # Compute raw BM25 scores
        scores = index.bm25.get_scores(query_tokens)

        # Set of allowed document IDs if filtering is applied
        doc_ids_filter: Optional[Set[str]] = (
            {str(d) for d in document_ids} if document_ids else None
        )

        candidates = []
        for chunk, score in zip(index.chunks, scores):
            if doc_ids_filter and chunk["document_id"] not in doc_ids_filter:
                continue
            # Keep matches with positive score
            if score > 0:
                candidates.append((chunk, float(score)))

        # Sort descending by BM25 score
        candidates.sort(key=lambda x: x[1], reverse=True)
        top_candidates = candidates[:top_k]

        results = []
        for chunk_data, score in top_candidates:
            results.append({
                "chunk_id": uuid.UUID(chunk_data["chunk_id"]),
                "document_id": uuid.UUID(chunk_data["document_id"]),
                "filename": chunk_data["filename"],
                "chunk_index": chunk_data["chunk_index"],
                "page_number": chunk_data["page_number"],
                "content": chunk_data["content"],
                "score": score,
                "metadata": chunk_data.get("metadata", {}),
            })
        return results
