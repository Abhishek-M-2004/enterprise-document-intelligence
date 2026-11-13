"""Document management and asynchronous ingestion endpoints."""

import math
from typing import Optional
from uuid import UUID
from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_tenant_context, require_header_role
from app.core.rate_limiter import upload_rate_limiter
from app.core.tenant_context import TenantContext
from app.db.session import get_db
from app.models.membership import Role
from app.schemas.auth import MessageResponse
from app.schemas.document import (
    DocumentDetailResponse,
    DocumentListResponse,
    DocumentResponse,
    DocumentStatusResponse,
)
from app.services.document_service import (
    DocumentNotFoundError,
    DocumentService,
    DocumentServiceError,
)

router = APIRouter()


@router.post(
    "/upload",
    response_model=DocumentResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Upload PDF Document",
    description=(
        "Upload a PDF document for an organization. Validates file signature, size limit (25 MB), "
        "stores the file securely, creates a database record, and queues Celery for asynchronous processing."
    ),
    dependencies=[Depends(upload_rate_limiter)],
)
async def upload_document(
    file: UploadFile = File(...),
    tenant_context: TenantContext = Depends(get_tenant_context),
    db: AsyncSession = Depends(get_db),
) -> DocumentResponse:
    """Upload and queue PDF document for ingestion."""
    service = DocumentService()
    try:
        document = await service.upload_document(
            db=db,
            tenant_id=tenant_context.tenant.id,
            user_id=tenant_context.user.id,
            file=file,
        )
        return DocumentResponse.model_validate(document)
    except DocumentServiceError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )


@router.get(
    "",
    response_model=DocumentListResponse,
    summary="List Organization Documents",
    description="Retrieve paginated documents belonging strictly to the authenticated tenant organization.",
)
async def list_documents(
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(20, ge=1, le=100, description="Items per page"),
    search: Optional[str] = Query(None, description="Filter by filename substring"),
    status_filter: Optional[str] = Query(None, alias="status", description="Filter by status (e.g. COMPLETED)"),
    tenant_context: TenantContext = Depends(get_tenant_context),
    db: AsyncSession = Depends(get_db),
) -> DocumentListResponse:
    """List documents for active tenant."""
    service = DocumentService()
    items, total = await service.list_documents(
        db=db,
        tenant_id=tenant_context.tenant.id,
        page=page,
        page_size=page_size,
        search=search,
        status=status_filter,
    )
    total_pages = math.ceil(total / page_size) if total > 0 else 0
    return DocumentListResponse(
        items=[DocumentResponse.model_validate(item) for item in items],
        total=total,
        page=page,
        page_size=page_size,
        total_pages=total_pages,
    )


@router.get(
    "/{document_id}",
    response_model=DocumentResponse,
    summary="Get Document Metadata",
    description="Retrieve document metadata ensuring cross-tenant isolation.",
)
async def get_document(
    document_id: UUID,
    tenant_context: TenantContext = Depends(get_tenant_context),
    db: AsyncSession = Depends(get_db),
) -> DocumentResponse:
    """Get single document metadata."""
    service = DocumentService()
    try:
        document = await service.get_document(
            db=db,
            tenant_id=tenant_context.tenant.id,
            document_id=document_id,
        )
        return DocumentResponse.model_validate(document)
    except DocumentNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found.",
        )


@router.get(
    "/{document_id}/file",
    summary="Download or Preview Document File",
    description="Streams the raw PDF file for in-browser preview or download, strictly verifying tenant ownership.",
)
async def get_document_file(
    document_id: UUID,
    tenant_context: TenantContext = Depends(get_tenant_context),
    db: AsyncSession = Depends(get_db),
):
    """Stream PDF document file for preview."""
    import os
    from fastapi.responses import FileResponse
    service = DocumentService()
    try:
        document = await service.get_document(
            db=db,
            tenant_id=tenant_context.tenant.id,
            document_id=document_id,
        )
        resolved_path = service.storage._resolve_path(document.storage_path)
        if not resolved_path.exists():
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Physical document file missing from storage.",
            )
        return FileResponse(
            path=str(resolved_path),
            media_type="application/pdf",
            filename=document.filename,
        )
    except DocumentNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found.",
        )


@router.get(
    "/{document_id}/detail",
    response_model=DocumentDetailResponse,
    summary="Get Document with Chunks",
    description="Retrieve document metadata and all extracted relational chunks.",
)
async def get_document_detail(
    document_id: UUID,
    tenant_context: TenantContext = Depends(get_tenant_context),
    db: AsyncSession = Depends(get_db),
) -> DocumentDetailResponse:
    """Get document and its relational chunks."""
    service = DocumentService()
    try:
        document = await service.get_document_with_chunks(
            db=db,
            tenant_id=tenant_context.tenant.id,
            document_id=document_id,
        )
        return DocumentDetailResponse.model_validate(document)
    except DocumentNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found.",
        )


@router.get(
    "/{document_id}/status",
    response_model=DocumentStatusResponse,
    summary="Get Processing Status",
    description="Polling endpoint returning current ingestion status, page count, and chunk count.",
)
async def get_document_status(
    document_id: UUID,
    tenant_context: TenantContext = Depends(get_tenant_context),
    db: AsyncSession = Depends(get_db),
) -> DocumentStatusResponse:
    """Poll processing status of a document."""
    service = DocumentService()
    try:
        document = await service.get_document(
            db=db,
            tenant_id=tenant_context.tenant.id,
            document_id=document_id,
        )
        return DocumentStatusResponse.model_validate(document)
    except DocumentNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found.",
        )


@router.delete(
    "/{document_id}",
    response_model=MessageResponse,
    summary="Delete Document",
    description=(
        "Permanently deletes document file from disk, its vector points from Qdrant, "
        "and relational chunk records from PostgreSQL. Requires OWNER or ADMIN role."
    ),
)
async def delete_document(
    document_id: UUID,
    tenant_context: TenantContext = Depends(require_header_role([Role.OWNER, Role.ADMIN])),
    db: AsyncSession = Depends(get_db),
) -> MessageResponse:
    """Delete document and all associated resources."""
    service = DocumentService()
    try:
        await service.delete_document(
            db=db,
            tenant_id=tenant_context.tenant.id,
            document_id=document_id,
        )
        return MessageResponse(
            message="Document, storage files, and vector indices deleted successfully."
        )
    except DocumentNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found.",
        )
