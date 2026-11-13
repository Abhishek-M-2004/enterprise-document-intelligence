"""Citation validation and extraction service verifying grounded source references."""

import re
from typing import Any, Dict, List, Set
from app.core.logging import get_logger
from app.services.context_builder import SourceContextItem

logger = get_logger(__name__)


class CitationService:
    """Extracts, validates, and resolves source citations from LLM generation outputs."""

    # Matches [S1], [S2], [S10], or combined [S1, S2] or [S1][S2]
    CITATION_REGEX = re.compile(r"\[(S\d+)(?:,\s*(S\d+))*\]")
    INDIVIDUAL_TAG_REGEX = re.compile(r"\bS\d+\b")

    @classmethod
    def extract_citation_tags(cls, answer_text: str) -> List[str]:
        """Extract all unique referenced source identifiers (e.g. ['S1', 'S2']) in appearance order."""
        if not answer_text:
            return []

        tags: List[str] = []
        seen: Set[str] = set()

        # Find all bracketed citation expressions like [S1] or [S1, S2]
        matches = re.findall(r"\[(?:S\d+(?:,\s*S\d+)*)\]", answer_text)
        for match in matches:
            for tag in cls.INDIVIDUAL_TAG_REGEX.findall(match):
                if tag not in seen:
                    seen.add(tag)
                    tags.append(tag)

        # Fallback check for isolated S1, S2 mentions
        if not tags:
            for tag in cls.INDIVIDUAL_TAG_REGEX.findall(answer_text):
                if tag not in seen:
                    seen.add(tag)
                    tags.append(tag)

        return tags

    @classmethod
    def validate_and_build_citations(
        cls,
        answer_text: str,
        sources_map: Dict[str, SourceContextItem],
    ) -> List[Dict[str, Any]]:
        """Validate referenced citation tags against the server-side sources map.
        
        Only permits citations corresponding to actual passages supplied to the LLM.
        All document metadata (filenames, page numbers, IDs) is populated exclusively
        from verified server-side objects to eliminate hallucinated provenance.
        """
        extracted_tags = cls.extract_citation_tags(answer_text)
        validated_citations: List[Dict[str, Any]] = []
        seen_tags: Set[str] = set()

        for tag in extracted_tags:
            if tag in seen_tags:
                continue
            seen_tags.add(tag)

            if tag in sources_map:
                source_item = sources_map[tag]
                validated_citations.append({
                    "source_id": tag,
                    "document_id": str(source_item.document_id),
                    "chunk_id": str(source_item.chunk_id),
                    "filename": source_item.filename,
                    "page_number": source_item.page_number,
                    "relevant_passage": source_item.passage[:300] + ("..." if len(source_item.passage) > 300 else ""),
                    "full_passage": source_item.passage,
                    "score": source_item.score,
                    "original_rank": source_item.original_rank,
                    "retrieval_sources": source_item.retrieval_sources,
                })
            else:
                logger.warning(
                    f"LLM hallucinated citation tag '[{tag}]' that was not provided in server context. "
                    f"Available tags: {list(sources_map.keys())}"
                )

        # If LLM didn't format brackets but sources exist and answer answered the question,
        # attach the primary top source as contextual attribution if needed
        if not validated_citations and sources_map and "could not be found" not in answer_text.lower():
            # Include the top S1 source as an inferred citation
            if "S1" in sources_map:
                top_item = sources_map["S1"]
                validated_citations.append({
                    "source_id": "S1",
                    "document_id": str(top_item.document_id),
                    "chunk_id": str(top_item.chunk_id),
                    "filename": top_item.filename,
                    "page_number": top_item.page_number,
                    "relevant_passage": top_item.passage[:300] + ("..." if len(top_item.passage) > 300 else ""),
                    "full_passage": top_item.passage,
                    "score": top_item.score,
                    "original_rank": top_item.original_rank,
                    "retrieval_sources": top_item.retrieval_sources,
                    "inferred": True,
                })

        return validated_citations
