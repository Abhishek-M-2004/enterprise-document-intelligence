"""Text chunking service with configurable chunk size and overlap."""

from dataclasses import dataclass, field
import re
from typing import Any, Dict, List, Optional

from app.core.config import settings
from app.core.logging import get_logger
from app.services.pdf_service import ExtractedDocument, ExtractedPage

logger = get_logger(__name__)


@dataclass
class TextChunk:
    """Represents a text chunk produced from extracted pages."""
    chunk_index: int
    page_number: Optional[int]
    content: str
    token_count: int
    metadata: Dict[str, Any] = field(default_factory=dict)


class ChunkingService:
    """Splits document text into overlapping chunks while preserving page provenance."""

    def __init__(
        self,
        chunk_size: Optional[int] = None,
        chunk_overlap: Optional[int] = None,
    ):
        self.chunk_size = chunk_size or settings.CHUNK_SIZE
        self.chunk_overlap = chunk_overlap or settings.CHUNK_OVERLAP
        if self.chunk_overlap >= self.chunk_size:
            raise ValueError("chunk_overlap must be strictly less than chunk_size")

    @staticmethod
    def estimate_tokens(text: str) -> int:
        """Estimate token count (approx. 4 characters per token or word count heuristic)."""
        if not text:
            return 0
        # Standard fast approximation: max(len(words), len(chars) // 4)
        words = text.split()
        return max(len(words), len(text) // 4)

    def _split_text_with_overlap(self, text: str) -> List[str]:
        """Split a long block of text into chunks of roughly chunk_size with chunk_overlap."""
        if not text or not text.strip():
            return []

        text = text.strip()
        if len(text) <= self.chunk_size:
            return [text]

        # Candidate split delimiters in order of preference
        delimiters = ["\n\n", "\n", ". ", "? ", "! ", "; ", ", ", " "]
        
        chunks: List[str] = []
        start = 0
        text_length = len(text)

        while start < text_length:
            end = min(start + self.chunk_size, text_length)

            if end < text_length:
                # Look for a clean natural break near the end
                split_point = -1
                window_start = max(start + (self.chunk_size // 2), start)
                sub_window = text[window_start:end]

                for delim in delimiters:
                    idx = sub_window.rfind(delim)
                    if idx != -1:
                        split_point = window_start + idx + len(delim)
                        break

                if split_point != -1:
                    end = split_point

            chunk_text = text[start:end].strip()
            if chunk_text:
                chunks.append(chunk_text)

            if end >= text_length:
                break

            # Slide start forward by chunk_size - chunk_overlap
            advance = max(1, (end - start) - self.chunk_overlap)
            start += advance

        return chunks

    def chunk_document(
        self,
        extracted_doc: ExtractedDocument,
        document_filename: Optional[str] = None,
    ) -> List[TextChunk]:
        """Chunk an extracted document while preserving page numbers and metadata."""
        chunks: List[TextChunk] = []
        chunk_index = 0

        for page in extracted_doc.pages:
            page_text = page.text.strip()
            if not page_text:
                continue

            page_chunks = self._split_text_with_overlap(page_text)
            for pc in page_chunks:
                tokens = self.estimate_tokens(pc)
                meta = {
                    "page_number": page.page_number,
                    "char_count": len(pc),
                    "filename": document_filename or "document.pdf",
                }
                chunks.append(
                    TextChunk(
                        chunk_index=chunk_index,
                        page_number=page.page_number,
                        content=pc,
                        token_count=tokens,
                        metadata=meta,
                    )
                )
                chunk_index += 1

        logger.info(
            "Document chunking completed",
            extra={
                "total_pages": extracted_doc.page_count,
                "total_chunks": len(chunks),
                "chunk_size": self.chunk_size,
                "chunk_overlap": self.chunk_overlap,
            },
        )
        return chunks
