"""API v1 root router aggregator."""

from fastapi import APIRouter
from app.api.v1.endpoints import auth, chat, documents, evaluation, health, search, tenants

api_router = APIRouter()

# Register core platform routes
api_router.include_router(health.router, tags=["Health"])
api_router.include_router(auth.router, prefix="/auth", tags=["Authentication"])
api_router.include_router(tenants.router, prefix="/tenants", tags=["Tenants & Memberships"])
api_router.include_router(documents.router, prefix="/documents", tags=["Documents & Ingestion"])
api_router.include_router(search.router, prefix="/search", tags=["Advanced Retrieval Engine"])
api_router.include_router(chat.router, prefix="/chat", tags=["RAG Chat & Q&A"])
api_router.include_router(evaluation.router, prefix="/evaluation", tags=["RAG Evaluation & Benchmarking"])
