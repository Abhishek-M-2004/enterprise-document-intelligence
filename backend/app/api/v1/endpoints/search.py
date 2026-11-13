"""Multi-strategy search endpoints for vector, BM25, and hybrid retrieval."""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_tenant_context
from app.core.rate_limiter import search_rate_limiter
from app.core.tenant_context import TenantContext
from app.db.session import get_db
from app.schemas.retrieval import RerankRequest, RetrievalRequest, SearchResponse
from app.services.retrieval_service import RetrievalService

router = APIRouter()


@router.post(
    "/vector",
    response_model=SearchResponse,
    summary="Semantic Vector Search",
    description="Retrieve document chunks using dense query embeddings and Qdrant cosine similarity search.",
    dependencies=[Depends(search_rate_limiter)],
)
async def vector_search(
    payload: RetrievalRequest,
    tenant_context: TenantContext = Depends(get_tenant_context),
    db: AsyncSession = Depends(get_db),
) -> SearchResponse:
    """Execute dense semantic search strictly isolated to the authenticated organization."""
    service = RetrievalService()
    try:
        response_data = await service.vector_search(
            db=db,
            tenant_id=tenant_context.tenant.id,
            query=payload.query,
            top_k=payload.top_k,
            document_ids=payload.document_ids,
        )
        return SearchResponse.model_validate(response_data)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )


@router.post(
    "/bm25",
    response_model=SearchResponse,
    summary="BM25 Lexical Keyword Search",
    description="Retrieve document chunks using BM25Okapi lexical keyword matching over tenant's persistent index.",
    dependencies=[Depends(search_rate_limiter)],
)
async def bm25_search(
    payload: RetrievalRequest,
    tenant_context: TenantContext = Depends(get_tenant_context),
    db: AsyncSession = Depends(get_db),
) -> SearchResponse:
    """Execute BM25 lexical keyword search strictly isolated to the authenticated organization."""
    service = RetrievalService()
    try:
        response_data = await service.bm25_search(
            db=db,
            tenant_id=tenant_context.tenant.id,
            query=payload.query,
            top_k=payload.top_k,
            document_ids=payload.document_ids,
        )
        return SearchResponse.model_validate(response_data)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )


@router.post(
    "/hybrid",
    response_model=SearchResponse,
    summary="Hybrid Retrieval with Reciprocal Rank Fusion",
    description=(
        "Executes dense vector search and BM25 lexical search independently, "
        "then fuses and deduplicates candidates using weighted Reciprocal Rank Fusion (RRF). "
        "Optionally passes candidates through BGE Cross-Encoder reranker when rerank=True."
    ),
    dependencies=[Depends(search_rate_limiter)],
)
async def hybrid_search(
    payload: RetrievalRequest,
    tenant_context: TenantContext = Depends(get_tenant_context),
    db: AsyncSession = Depends(get_db),
) -> SearchResponse:
    """Execute hybrid retrieval combining semantic and lexical ranking, with optional neural reranking."""
    service = RetrievalService()
    try:
        response_data = await service.hybrid_search(
            db=db,
            tenant_id=tenant_context.tenant.id,
            query=payload.query,
            top_k=payload.top_k,
            document_ids=payload.document_ids,
            rerank=payload.rerank,
            rerank_candidates=payload.rerank_candidates,
        )
        return SearchResponse.model_validate(response_data)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )


@router.post(
    "/rerank",
    response_model=SearchResponse,
    summary="Neural Cross-Encoder Reranking",
    description=(
        "Generates preliminary candidate passages via Hybrid RRF search, then applies "
        "BAAI/bge-reranker-base cross-encoder model to produce a refined relevance ordering."
    ),
    dependencies=[Depends(search_rate_limiter)],
)
async def rerank_search(
    payload: RerankRequest,
    tenant_context: TenantContext = Depends(get_tenant_context),
    db: AsyncSession = Depends(get_db),
) -> SearchResponse:
    """Execute hybrid retrieval followed by neural cross-encoder reranking strictly isolated to the tenant."""
    service = RetrievalService()
    try:
        response_data = await service.hybrid_search_with_reranking(
            db=db,
            tenant_id=tenant_context.tenant.id,
            query=payload.query,
            top_k=payload.top_k,
            candidate_top_k=payload.candidate_top_k,
            document_ids=payload.document_ids,
        )
        return SearchResponse.model_validate(response_data)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )
