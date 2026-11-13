"""Chat endpoints for persistent conversational RAG sessions, stateless Q&A, and SSE streaming."""

import json
from typing import Any, AsyncGenerator, List
import uuid
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.dependencies import get_current_user, get_tenant_context
from app.core.rate_limiter import chat_rate_limiter
from app.core.tenant_context import TenantContext
from app.db.session import get_db
from app.models.chat import ChatMessage, ChatSession
from app.models.user import User
from app.schemas.chat import (
    AskQuestionRequest,
    ChatMessageResponse,
    ChatSessionCreate,
    ChatSessionDetailResponse,
    ChatSessionResponse,
    RAGResponse,
    SendMessageRequest,
)
from app.services.rag_service import RAGService

router = APIRouter()


@router.post(
    "/sessions",
    response_model=ChatSessionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create Chat Session",
    description="Initialize a new persistent conversation thread within the active tenant organization.",
)
async def create_chat_session(
    payload: ChatSessionCreate,
    tenant_context: TenantContext = Depends(get_tenant_context),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ChatSessionResponse:
    """Create a new chat session scoped strictly to the authenticated tenant and user."""
    session = ChatSession(
        tenant_id=tenant_context.tenant.id,
        user_id=current_user.id,
        title=payload.title or "New Conversation",
    )
    db.add(session)
    await db.commit()
    await db.refresh(session)
    return ChatSessionResponse(
        id=session.id,
        tenant_id=session.tenant_id,
        user_id=session.user_id,
        title=session.title,
        created_at=session.created_at,
        updated_at=session.updated_at,
        message_count=0,
    )


@router.get(
    "/sessions",
    response_model=List[ChatSessionResponse],
    summary="List Chat Sessions",
    description="List all conversation threads belonging to the authenticated user in the current tenant.",
)
async def list_chat_sessions(
    tenant_context: TenantContext = Depends(get_tenant_context),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> List[ChatSessionResponse]:
    """Retrieve chat sessions for current user in active tenant."""
    stmt = (
        select(ChatSession, func.count(ChatMessage.id).label("msg_count"))
        .outerjoin(ChatMessage, ChatMessage.session_id == ChatSession.id)
        .where(
            ChatSession.tenant_id == tenant_context.tenant.id,
            ChatSession.user_id == current_user.id,
        )
        .group_by(ChatSession.id)
        .order_by(ChatSession.updated_at.desc())
    )
    result = await db.execute(stmt)
    rows = result.all()

    items = []
    for session, msg_count in rows:
        items.append(
            ChatSessionResponse(
                id=session.id,
                tenant_id=session.tenant_id,
                user_id=session.user_id,
                title=session.title,
                created_at=session.created_at,
                updated_at=session.updated_at,
                message_count=msg_count,
            )
        )
    return items


@router.get(
    "/sessions/{session_id}",
    response_model=ChatSessionDetailResponse,
    summary="Get Chat Session Detail",
    description="Retrieve a chat session and its complete chronological message history.",
)
async def get_chat_session(
    session_id: uuid.UUID,
    tenant_context: TenantContext = Depends(get_tenant_context),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ChatSessionDetailResponse:
    """Retrieve a conversation thread ensuring strict tenant and user ownership."""
    stmt = (
        select(ChatSession)
        .options(selectinload(ChatSession.messages))
        .where(
            ChatSession.id == session_id,
            ChatSession.tenant_id == tenant_context.tenant.id,
            ChatSession.user_id == current_user.id,
        )
    )
    res = await db.execute(stmt)
    session = res.scalar_one_or_none()

    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Chat session not found or does not belong to this organization.",
        )

    return ChatSessionDetailResponse(
        id=session.id,
        tenant_id=session.tenant_id,
        user_id=session.user_id,
        title=session.title,
        created_at=session.created_at,
        updated_at=session.updated_at,
        message_count=len(session.messages),
        messages=[
            ChatMessageResponse(
                id=m.id,
                session_id=m.session_id,
                role=m.role,
                content=m.content,
                citations=m.citations,
                message_metadata=m.message_metadata,
                created_at=m.created_at,
            )
            for m in session.messages
        ],
    )


@router.delete(
    "/sessions/{session_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete Chat Session",
    description="Permanently delete a conversation thread and its associated message history.",
)
async def delete_chat_session(
    session_id: uuid.UUID,
    tenant_context: TenantContext = Depends(get_tenant_context),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Delete chat session with cascade deletion of messages."""
    stmt = select(ChatSession).where(
        ChatSession.id == session_id,
        ChatSession.tenant_id == tenant_context.tenant.id,
        ChatSession.user_id == current_user.id,
    )
    res = await db.execute(stmt)
    session = res.scalar_one_or_none()
    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Chat session not found.",
        )

    await db.delete(session)
    await db.commit()


@router.post(
    "/sessions/{session_id}/messages",
    response_model=RAGResponse,
    summary="Send Chat Message (Synchronous)",
    description="Post a user query to an existing session, execute RAG pipeline, and generate an answer with citations.",
    dependencies=[Depends(chat_rate_limiter)],
)
async def send_chat_message(
    session_id: uuid.UUID,
    payload: SendMessageRequest,
    tenant_context: TenantContext = Depends(get_tenant_context),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> RAGResponse:
    """Execute complete RAG pipeline and append exchange to conversation history."""
    rag_service = RAGService()
    try:
        response_data = await rag_service.answer_question(
            db=db,
            tenant_id=tenant_context.tenant.id,
            user_id=current_user.id,
            query=payload.content,
            session_id=session_id,
            document_ids=payload.document_ids,
            top_k=payload.top_k,
            candidate_top_k=payload.candidate_top_k,
            temperature=payload.temperature,
        )
        return RAGResponse.model_validate(response_data)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )


@router.post(
    "/sessions/{session_id}/messages/stream",
    summary="Stream Chat Message (Server-Sent Events)",
    description="Stream RAG answer generation tokens in real time, followed by verified citation metadata.",
    dependencies=[Depends(chat_rate_limiter)],
)
async def stream_chat_message(
    session_id: uuid.UUID,
    payload: SendMessageRequest,
    tenant_context: TenantContext = Depends(get_tenant_context),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> StreamingResponse:
    """Stream response tokens using Server-Sent Events (SSE)."""
    rag_service = RAGService()

    async def event_generator() -> AsyncGenerator[str, None]:
        try:
            async for chunk in rag_service.answer_question_stream(
                db=db,
                tenant_id=tenant_context.tenant.id,
                user_id=current_user.id,
                query=payload.content,
                session_id=session_id,
                document_ids=payload.document_ids,
                top_k=payload.top_k,
                candidate_top_k=payload.candidate_top_k,
                temperature=payload.temperature,
            ):
                event_name = chunk.get("event", "message")
                data_payload = chunk.get("data", "")
                if isinstance(data_payload, (dict, list)):
                    data_str = json.dumps(data_payload)
                else:
                    data_str = str(data_payload)

                yield f"event: {event_name}\ndata: {data_str}\n\n"
        except Exception as e:
            err_data = json.dumps({"error": str(e)})
            yield f"event: error\ndata: {err_data}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post(
    "/ask",
    response_model=RAGResponse,
    summary="One-off Stateless Question Answering",
    description="Ask a direct question across uploaded organization documents without managing a persistent chat thread.",
    dependencies=[Depends(chat_rate_limiter)],
)
async def ask_stateless_question(
    payload: AskQuestionRequest,
    tenant_context: TenantContext = Depends(get_tenant_context),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> RAGResponse:
    """Execute stateless RAG question-answering strictly within tenant boundaries."""
    rag_service = RAGService()
    try:
        response_data = await rag_service.answer_question(
            db=db,
            tenant_id=tenant_context.tenant.id,
            user_id=current_user.id,
            query=payload.query,
            session_id=None,
            document_ids=payload.document_ids,
            top_k=payload.top_k,
            candidate_top_k=payload.candidate_top_k,
            temperature=payload.temperature,
        )
        return RAGResponse.model_validate(response_data)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )
