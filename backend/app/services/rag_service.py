"""Full RAG Pipeline Orchestrator coordinating retrieval, reranking, context, LLM, and citations."""

import time
from typing import Any, AsyncGenerator, Dict, List, Optional
import uuid
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging import get_logger
from app.core.prompts import RAG_PROMPT_VERSION, format_conversation_messages
from app.models.chat import ChatMessage, ChatSession, MessageRole
from app.services.citation_service import CitationService
from app.services.context_builder import ContextBuilder
from app.services.llm_service import LLMService
from app.services.retrieval_service import RetrievalService

logger = get_logger(__name__)


class RAGService:
    """Orchestrates end-to-end Retrieval-Augmented Generation for enterprise queries."""

    def __init__(self):
        self.retrieval_service = RetrievalService()
        self.llm_service = LLMService.get_instance()

    @staticmethod
    def generate_followup_suggestions(query: str, citations: List[Dict[str, Any]]) -> List[str]:
        """Generate smart follow-up suggestions based on retrieved sources."""
        suggestions = []
        if citations:
            top_file = citations[0].get("filename", "")
            if top_file:
                suggestions.append(f"Can you summarize the key findings in {top_file}?")
            suggestions.append("What are the specific requirements or exceptions mentioned?")
            suggestions.append("Are there any related policies or dependencies in these documents?")
        else:
            suggestions.append("Which documents should I upload to answer this question?")
            suggestions.append("Can you clarify what topics are covered in the uploaded files?")
        return suggestions[:3]

    async def answer_question(
        self,
        db: AsyncSession,
        tenant_id: uuid.UUID,
        user_id: uuid.UUID,
        query: str,
        session_id: Optional[uuid.UUID] = None,
        document_ids: Optional[List[uuid.UUID]] = None,
        top_k: int = 5,
        candidate_top_k: int = 30,
        temperature: Optional[float] = None,
    ) -> Dict[str, Any]:
        """Execute end-to-end synchronous RAG answer generation with citation verification."""
        start_total = time.perf_counter()

        if not query or not query.strip():
            raise ValueError("Query string cannot be empty or whitespace-only.")

        clean_query = query.strip()

        # 1. Fetch conversation history if session is active
        history_messages: List[Dict[str, str]] = []
        session_obj: Optional[ChatSession] = None
        if session_id:
            stmt = select(ChatSession).where(
                ChatSession.id == session_id,
                ChatSession.tenant_id == tenant_id,
            )
            res = await db.execute(stmt)
            session_obj = res.scalar_one_or_none()
            if not session_obj:
                raise ValueError("Chat session not found or does not belong to this organization.")

            # Load recent messages
            msg_stmt = (
                select(ChatMessage)
                .where(ChatMessage.session_id == session_id)
                .order_by(ChatMessage.created_at.asc())
            )
            msg_res = await db.execute(msg_stmt)
            past_messages = msg_res.scalars().all()
            for m in past_messages:
                history_messages.append({"role": m.role, "content": m.content})

        # 2. Execute Hybrid Retrieval & BGE Cross-Encoder Reranking
        retrieval_res = await self.retrieval_service.hybrid_search_with_reranking(
            db=db,
            tenant_id=tenant_id,
            query=clean_query,
            top_k=top_k,
            candidate_top_k=candidate_top_k,
            document_ids=document_ids,
        )

        candidates = retrieval_res.get("results", [])
        metrics = retrieval_res.get("metrics", {})

        # 3. Build Context block with stable source IDs
        t_ctx_start = time.perf_counter()
        built_context = ContextBuilder.build_context(
            candidates=candidates,
            max_tokens=settings.MAX_CONTEXT_TOKENS,
        )
        context_build_ms = round((time.perf_counter() - t_ctx_start) * 1000, 2)

        # 4. Format Prompt Messages with Anti-Injection Rules & Bounded History
        prompt_messages = format_conversation_messages(
            query=clean_query,
            context_text=built_context.context_text,
            history=history_messages,
        )

        # 5. Call LLM for generation
        t_llm_start = time.perf_counter()
        llm_response = await self.llm_service.generate_answer(
            messages=prompt_messages,
            temperature=temperature,
        )
        llm_gen_ms = round((time.perf_counter() - t_llm_start) * 1000, 2)
        answer_text = llm_response.get("content", "")

        # 6. Extract and Validate Citations against server-side sources
        validated_citations = CitationService.validate_and_build_citations(
            answer_text=answer_text,
            sources_map=built_context.sources_map,
        )

        total_latency_ms = round((time.perf_counter() - start_total) * 1000, 2)

        rag_metrics = {
            "query_embedding_ms": metrics.get("query_embedding_ms"),
            "vector_search_ms": metrics.get("vector_search_ms"),
            "bm25_search_ms": metrics.get("bm25_search_ms"),
            "rrf_fusion_ms": metrics.get("rrf_fusion_ms"),
            "rerank_ms": metrics.get("rerank_ms"),
            "context_building_ms": context_build_ms,
            "llm_generation_ms": llm_gen_ms,
            "total_latency_ms": total_latency_ms,
            "retrieved_candidates_count": metrics.get("candidate_count", len(candidates)),
            "reranked_chunks_count": len(candidates),
            "context_passages_count": built_context.passages_included,
            "prompt_tokens": llm_response.get("usage", {}).get("prompt_tokens"),
            "completion_tokens": llm_response.get("usage", {}).get("completion_tokens"),
            "total_tokens": llm_response.get("usage", {}).get("total_tokens"),
            "prompt_version": RAG_PROMPT_VERSION,
            "model": llm_response.get("model", settings.LLM_MODEL),
        }

        # 7. Persist messages in database if in a persistent session
        if session_obj:
            user_msg = ChatMessage(
                session_id=session_obj.id,
                tenant_id=tenant_id,
                role=MessageRole.USER.value,
                content=clean_query,
                citations=[],
                message_metadata={},
            )
            assistant_msg = ChatMessage(
                session_id=session_obj.id,
                tenant_id=tenant_id,
                role=MessageRole.ASSISTANT.value,
                content=answer_text,
                citations=validated_citations,
                message_metadata=rag_metrics,
            )
            db.add(user_msg)
            db.add(assistant_msg)

            # Auto-update session title if it's currently the default
            if session_obj.title == "New Conversation":
                session_obj.title = clean_query[:50] + ("..." if len(clean_query) > 50 else "")

            await db.commit()

        followups = self.generate_followup_suggestions(clean_query, validated_citations)

        return {
            "answer": answer_text,
            "citations": validated_citations,
            "metrics": rag_metrics,
            "followup_suggestions": followups,
            "session_id": str(session_id) if session_id else None,
        }

    async def answer_question_stream(
        self,
        db: AsyncSession,
        tenant_id: uuid.UUID,
        user_id: uuid.UUID,
        query: str,
        session_id: Optional[uuid.UUID] = None,
        document_ids: Optional[List[uuid.UUID]] = None,
        top_k: int = 5,
        candidate_top_k: int = 30,
        temperature: Optional[float] = None,
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """Stream answer tokens followed by final verified citations and telemetry."""
        start_total = time.perf_counter()

        if not query or not query.strip():
            yield {"event": "error", "data": "Query string cannot be empty."}
            return

        clean_query = query.strip()

        # 1. Fetch conversation history if session is active
        history_messages: List[Dict[str, str]] = []
        session_obj: Optional[ChatSession] = None
        if session_id:
            stmt = select(ChatSession).where(
                ChatSession.id == session_id,
                ChatSession.tenant_id == tenant_id,
            )
            res = await db.execute(stmt)
            session_obj = res.scalar_one_or_none()
            if not session_obj:
                yield {"event": "error", "data": "Chat session not found."}
                return

            msg_stmt = (
                select(ChatMessage)
                .where(ChatMessage.session_id == session_id)
                .order_by(ChatMessage.created_at.asc())
            )
            msg_res = await db.execute(msg_stmt)
            past_messages = msg_res.scalars().all()
            for m in past_messages:
                history_messages.append({"role": m.role, "content": m.content})

        # 2. Retrieve & Rerank Candidates
        yield {"event": "status", "data": "Retrieving and reranking relevant document passages..."}
        retrieval_res = await self.retrieval_service.hybrid_search_with_reranking(
            db=db,
            tenant_id=tenant_id,
            query=clean_query,
            top_k=top_k,
            candidate_top_k=candidate_top_k,
            document_ids=document_ids,
        )
        candidates = retrieval_res.get("results", [])
        metrics = retrieval_res.get("metrics", {})

        # 3. Context Construction
        t_ctx = time.perf_counter()
        built_context = ContextBuilder.build_context(
            candidates=candidates,
            max_tokens=settings.MAX_CONTEXT_TOKENS,
        )
        ctx_ms = round((time.perf_counter() - t_ctx) * 1000, 2)

        prompt_messages = format_conversation_messages(
            query=clean_query,
            context_text=built_context.context_text,
            history=history_messages,
        )

        # 4. Stream Tokens from LLM
        accumulated_answer: List[str] = []
        t_llm = time.perf_counter()
        async for token in self.llm_service.generate_answer_stream(
            messages=prompt_messages,
            temperature=temperature,
        ):
            accumulated_answer.append(token)
            yield {"event": "token", "data": token}

        llm_gen_ms = round((time.perf_counter() - t_llm) * 1000, 2)
        full_answer = "".join(accumulated_answer)

        # 5. Citation validation
        validated_citations = CitationService.validate_and_build_citations(
            answer_text=full_answer,
            sources_map=built_context.sources_map,
        )

        total_latency_ms = round((time.perf_counter() - start_total) * 1000, 2)

        rag_metrics = {
            "query_embedding_ms": metrics.get("query_embedding_ms"),
            "vector_search_ms": metrics.get("vector_search_ms"),
            "bm25_search_ms": metrics.get("bm25_search_ms"),
            "rrf_fusion_ms": metrics.get("rrf_fusion_ms"),
            "rerank_ms": metrics.get("rerank_ms"),
            "context_building_ms": ctx_ms,
            "llm_generation_ms": llm_gen_ms,
            "total_latency_ms": total_latency_ms,
            "retrieved_candidates_count": metrics.get("candidate_count", len(candidates)),
            "reranked_chunks_count": len(candidates),
            "context_passages_count": built_context.passages_included,
            "prompt_version": RAG_PROMPT_VERSION,
        }

        # 6. Persist to DB on successful completion
        if session_obj:
            user_msg = ChatMessage(
                session_id=session_obj.id,
                tenant_id=tenant_id,
                role=MessageRole.USER.value,
                content=clean_query,
                citations=[],
                message_metadata={},
            )
            assistant_msg = ChatMessage(
                session_id=session_obj.id,
                tenant_id=tenant_id,
                role=MessageRole.ASSISTANT.value,
                content=full_answer,
                citations=validated_citations,
                message_metadata=rag_metrics,
            )
            db.add(user_msg)
            db.add(assistant_msg)
            if session_obj.title == "New Conversation":
                session_obj.title = clean_query[:50] + ("..." if len(clean_query) > 50 else "")
            await db.commit()

        followups = self.generate_followup_suggestions(clean_query, validated_citations)

        # 7. Final structured completion event
        yield {
            "event": "done",
            "data": {
                "citations": validated_citations,
                "metrics": rag_metrics,
                "followup_suggestions": followups,
                "session_id": str(session_id) if session_id else None,
            },
        }
