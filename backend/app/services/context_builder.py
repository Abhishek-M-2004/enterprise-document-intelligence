"""Context construction service for RAG pipelines with token budgeting and citation tracking."""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set
import uuid

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)


@dataclass
class SourceContextItem:
    """Rich metadata and text passage for an included source citation."""
    source_id: str
    document_id: uuid.UUID
    chunk_id: uuid.UUID
    filename: str
    page_number: Optional[int]
    passage: str
    score: Optional[float]
    original_rank: Optional[int]
    retrieval_sources: str
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Serialize source context item to dictionary."""
        return {
            "source_id": self.source_id,
            "document_id": str(self.document_id),
            "chunk_id": str(self.chunk_id),
            "filename": self.filename,
            "page_number": self.page_number,
            "passage": self.passage,
            "score": self.score,
            "original_rank": self.original_rank,
            "retrieval_sources": self.retrieval_sources,
            "metadata": self.metadata,
        }


@dataclass
class BuiltContext:
    """Structured context output ready for prompt construction and citation validation."""
    context_text: str
    sources_map: Dict[str, SourceContextItem]
    total_tokens_estimate: int
    passages_included: int
    passages_considered: int


class ContextBuilder:
    """Builds token-bounded, deduplicated context blocks from reranked passages.
    
    Assigns stable source identifiers ([SOURCE: S1], [SOURCE: S2]) that the LLM
    references, enabling server-side citation validation and deep traceability.
    """

    @staticmethod
    def estimate_tokens(text: str) -> int:
        """Estimate token count based on standard ~4 chars per token rule of thumb."""
        if not text:
            return 0
        return max(1, len(text) // 4)

    @classmethod
    def build_context(
        cls,
        candidates: List[Dict[str, Any]],
        max_tokens: Optional[int] = None,
    ) -> BuiltContext:
        """Construct prompt context block within token limit from ranked candidates.
        
        Prioritizes top-ranked passages and ensures passages are deduplicated.
        """
        token_budget = max_tokens or settings.MAX_CONTEXT_TOKENS
        sources_map: Dict[str, SourceContextItem] = {}
        context_blocks: List[str] = []
        seen_chunk_ids: Set[str] = set()
        seen_contents: Set[str] = set()
        current_token_count = 0

        for cand in candidates:
            chunk_id_str = str(cand.get("chunk_id", ""))
            content = str(cand.get("content", "")).strip()

            # Skip empty or duplicate chunks
            if not content:
                continue
            if chunk_id_str and chunk_id_str in seen_chunk_ids:
                continue
            if content in seen_contents:
                continue

            # Estimate token requirement for this passage block
            source_index = len(sources_map) + 1
            source_tag = f"S{source_index}"
            filename = cand.get("filename", "document.pdf")
            page_num = cand.get("page_number")
            page_str = f"Page {page_num}" if page_num is not None else "Page N/A"

            block_text = (
                f"[SOURCE: {source_tag}]\n"
                f"Document: {filename}\n"
                f"{page_str}\n"
                f"Content:\n{content}\n"
            )

            block_tokens = cls.estimate_tokens(block_text)

            # Check if adding this passage exceeds budget
            if current_token_count + block_tokens > token_budget and len(context_blocks) > 0:
                logger.debug(
                    f"Context budget reached ({current_token_count} + {block_tokens} > {token_budget}). "
                    f"Truncating at {len(context_blocks)} passages."
                )
                break

            seen_chunk_ids.add(chunk_id_str)
            seen_contents.add(content)
            context_blocks.append(block_text)
            current_token_count += block_tokens

            doc_id = cand.get("document_id")
            if isinstance(doc_id, str):
                doc_id = uuid.UUID(doc_id)
            elif doc_id is None:
                doc_id = uuid.uuid4()

            chunk_id = cand.get("chunk_id")
            if isinstance(chunk_id, str):
                chunk_id = uuid.UUID(chunk_id)
            elif chunk_id is None:
                chunk_id = uuid.uuid4()

            sources_map[source_tag] = SourceContextItem(
                source_id=source_tag,
                document_id=doc_id,
                chunk_id=chunk_id,
                filename=filename,
                page_number=page_num,
                passage=content,
                score=cand.get("reranker_score") or cand.get("score") or cand.get("rrf_score"),
                original_rank=cand.get("original_rank"),
                retrieval_sources=cand.get("retrieval_sources", "unknown"),
                metadata=cand.get("metadata", {}),
            )

        full_context_text = "\n---\n".join(context_blocks) if context_blocks else ""

        return BuiltContext(
            context_text=full_context_text,
            sources_map=sources_map,
            total_tokens_estimate=current_token_count,
            passages_included=len(context_blocks),
            passages_considered=len(candidates),
        )
