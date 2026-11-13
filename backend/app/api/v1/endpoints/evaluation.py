"""Evaluation and Benchmarking API endpoints for Ragas quality assessment."""

from typing import List, Optional
import uuid
from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.dependencies import get_tenant_context
from app.core.rate_limiter import evaluation_rate_limiter
from app.core.tenant_context import TenantContext
from app.db.session import get_db
from app.models.evaluation import (
    EvaluationDataset,
    EvaluationResult,
    EvaluationRun,
    EvaluationSample,
    RetrievalStrategy,
)
from app.schemas.evaluation import (
    DatasetCreateRequest,
    DatasetResponse,
    ResultResponse,
    RunCreateRequest,
    RunResponse,
    SampleCreateRequest,
    SampleImportResponse,
    SampleResponse,
    SampleUpdateRequest,
    StrategyComparisonResponse,
)
from app.services.evaluation_service import EvaluationService

router = APIRouter()


# ------------------------------------------------------------------------------
# Dataset Management Endpoints
# ------------------------------------------------------------------------------

@router.post(
    "/datasets",
    response_model=DatasetResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create Evaluation Dataset",
    description="Provision a new tenant-isolated benchmark dataset for repeatable RAG evaluations.",
    dependencies=[Depends(evaluation_rate_limiter)],
)
async def create_dataset(
    payload: DatasetCreateRequest,
    tenant_context: TenantContext = Depends(get_tenant_context),
    db: AsyncSession = Depends(get_db),
) -> DatasetResponse:
    """Create a new evaluation dataset."""
    service = EvaluationService()
    try:
        dataset = await service.create_dataset(
            db=db,
            tenant_id=tenant_context.tenant.id,
            name=payload.name,
            description=payload.description,
            version=payload.version,
        )
        return DatasetResponse(
            id=dataset.id,
            tenant_id=dataset.tenant_id,
            name=dataset.name,
            description=dataset.description,
            version=dataset.version,
            sample_count=0,
            created_at=dataset.created_at,
            updated_at=dataset.updated_at,
        )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.post(
    "/datasets/synthetic",
    response_model=DatasetResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Generate Synthetic Benchmark Dataset",
    description="Creates a verified baseline dataset with built-in ground-truth answers for instant local evaluation.",
    dependencies=[Depends(evaluation_rate_limiter)],
)
async def create_synthetic_dataset(
    name: str = Query("Platform Baseline Benchmark", description="Title for synthetic dataset."),
    tenant_context: TenantContext = Depends(get_tenant_context),
    db: AsyncSession = Depends(get_db),
) -> DatasetResponse:
    """Generate synthetic development dataset."""
    service = EvaluationService()
    dataset = await service.create_synthetic_dataset(
        db=db,
        tenant_id=tenant_context.tenant.id,
        name=name,
    )
    return DatasetResponse(
        id=dataset.id,
        tenant_id=dataset.tenant_id,
        name=dataset.name,
        description=dataset.description,
        version=dataset.version,
        sample_count=3,
        created_at=dataset.created_at,
        updated_at=dataset.updated_at,
    )


@router.get(
    "/datasets",
    response_model=List[DatasetResponse],
    summary="List Evaluation Datasets",
    description="Retrieve all evaluation datasets owned by the authenticated tenant organization.",
)
async def list_datasets(
    tenant_context: TenantContext = Depends(get_tenant_context),
    db: AsyncSession = Depends(get_db),
) -> List[DatasetResponse]:
    """List tenant datasets with sample counts."""
    stmt = (
        select(
            EvaluationDataset,
            func.count(EvaluationSample.id).label("sample_count"),
        )
        .outerjoin(EvaluationSample, EvaluationSample.dataset_id == EvaluationDataset.id)
        .where(EvaluationDataset.tenant_id == tenant_context.tenant.id)
        .group_by(EvaluationDataset.id)
        .order_by(EvaluationDataset.created_at.desc())
    )
    res = await db.execute(stmt)
    records = res.all()

    return [
        DatasetResponse(
            id=d.id,
            tenant_id=d.tenant_id,
            name=d.name,
            description=d.description,
            version=d.version,
            sample_count=cnt,
            created_at=d.created_at,
            updated_at=d.updated_at,
        )
        for d, cnt in records
    ]


@router.get(
    "/datasets/{dataset_id}",
    response_model=DatasetResponse,
    summary="Get Evaluation Dataset",
    description="Retrieve dataset details by ID.",
)
async def get_dataset(
    dataset_id: uuid.UUID,
    tenant_context: TenantContext = Depends(get_tenant_context),
    db: AsyncSession = Depends(get_db),
) -> DatasetResponse:
    """Fetch single evaluation dataset."""
    stmt = (
        select(
            EvaluationDataset,
            func.count(EvaluationSample.id).label("sample_count"),
        )
        .outerjoin(EvaluationSample, EvaluationSample.dataset_id == EvaluationDataset.id)
        .where(
            EvaluationDataset.id == dataset_id,
            EvaluationDataset.tenant_id == tenant_context.tenant.id,
        )
        .group_by(EvaluationDataset.id)
    )
    res = await db.execute(stmt)
    row = res.first()
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Dataset not found.")

    d, cnt = row
    return DatasetResponse(
        id=d.id,
        tenant_id=d.tenant_id,
        name=d.name,
        description=d.description,
        version=d.version,
        sample_count=cnt,
        created_at=d.created_at,
        updated_at=d.updated_at,
    )


@router.post(
    "/datasets/{dataset_id}/samples",
    response_model=SampleResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Add Evaluation Sample",
    description="Add a single question and reference ground-truth answer to an existing dataset.",
    dependencies=[Depends(evaluation_rate_limiter)],
)
async def add_sample(
    dataset_id: uuid.UUID,
    payload: SampleCreateRequest,
    tenant_context: TenantContext = Depends(get_tenant_context),
    db: AsyncSession = Depends(get_db),
) -> SampleResponse:
    """Add evaluation sample."""
    service = EvaluationService()
    try:
        sample = await service.add_sample(
            db=db,
            tenant_id=tenant_context.tenant.id,
            dataset_id=dataset_id,
            question=payload.question,
            ground_truth=payload.ground_truth,
            reference_contexts=payload.reference_contexts,
            relevant_document_ids=payload.relevant_document_ids,
            sample_metadata=payload.sample_metadata,
        )
        return SampleResponse.model_validate(sample)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.get(
    "/datasets/{dataset_id}/samples",
    response_model=List[SampleResponse],
    summary="List Dataset Samples",
    description="List all evaluation questions and ground-truth answers in a dataset.",
)
async def list_samples(
    dataset_id: uuid.UUID,
    tenant_context: TenantContext = Depends(get_tenant_context),
    db: AsyncSession = Depends(get_db),
) -> List[SampleResponse]:
    """Retrieve samples for dataset."""
    stmt = (
        select(EvaluationSample)
        .where(
            EvaluationSample.dataset_id == dataset_id,
            EvaluationSample.tenant_id == tenant_context.tenant.id,
        )
        .order_by(EvaluationSample.created_at)
    )
    res = await db.execute(stmt)
    samples = res.scalars().all()
    return [SampleResponse.model_validate(s) for s in samples]


@router.put(
    "/datasets/{dataset_id}/samples/{sample_id}",
    response_model=SampleResponse,
    summary="Update Sample Reference Data",
    description="Mechanism for human review and correction of ground-truth reference answers and contexts.",
)
async def update_sample(
    dataset_id: uuid.UUID,
    sample_id: uuid.UUID,
    payload: SampleUpdateRequest,
    tenant_context: TenantContext = Depends(get_tenant_context),
    db: AsyncSession = Depends(get_db),
) -> SampleResponse:
    """Update reference ground-truth data."""
    service = EvaluationService()
    try:
        sample = await service.update_sample(
            db=db,
            tenant_id=tenant_context.tenant.id,
            sample_id=sample_id,
            ground_truth=payload.ground_truth,
            reference_contexts=payload.reference_contexts,
            sample_metadata=payload.sample_metadata,
        )
        return SampleResponse.model_validate(sample)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.post(
    "/datasets/{dataset_id}/import",
    response_model=SampleImportResponse,
    summary="Import Samples (CSV or JSON)",
    description="Bulk import evaluation samples from uploaded CSV or JSON file.",
    dependencies=[Depends(evaluation_rate_limiter)],
)
async def import_samples(
    dataset_id: uuid.UUID,
    file: UploadFile = File(...),
    tenant_context: TenantContext = Depends(get_tenant_context),
    db: AsyncSession = Depends(get_db),
) -> SampleImportResponse:
    """Import samples from file."""
    # Verify dataset exists and belongs to tenant
    stmt = select(EvaluationDataset).where(
        EvaluationDataset.id == dataset_id,
        EvaluationDataset.tenant_id == tenant_context.tenant.id,
    )
    res = await db.execute(stmt)
    if not res.scalar_one_or_none():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Dataset not found.")

    content_bytes = await file.read()
    content_str = content_bytes.decode("utf-8", errors="replace")
    filename = (file.filename or "").lower()

    service = EvaluationService()
    try:
        if filename.endswith(".json"):
            success_count, errors = await service.import_samples_from_json(
                db=db,
                tenant_id=tenant_context.tenant.id,
                dataset_id=dataset_id,
                json_content=content_str,
            )
        elif filename.endswith(".csv"):
            success_count, errors = await service.import_samples_from_csv(
                db=db,
                tenant_id=tenant_context.tenant.id,
                dataset_id=dataset_id,
                csv_content=content_str,
            )
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Unsupported file format. Please upload a .json or .csv dataset file.",
            )

        return SampleImportResponse(
            success_count=success_count,
            error_count=len(errors),
            errors=errors,
        )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


# ------------------------------------------------------------------------------
# Evaluation Execution Endpoints
# ------------------------------------------------------------------------------

@router.post(
    "/runs",
    response_model=RunResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Execute Benchmark Evaluation Run",
    description="Launch an evaluation run evaluating a designated retrieval strategy against a dataset.",
    dependencies=[Depends(evaluation_rate_limiter)],
)
async def create_evaluation_run(
    payload: RunCreateRequest,
    tenant_context: TenantContext = Depends(get_tenant_context),
    db: AsyncSession = Depends(get_db),
) -> RunResponse:
    """Execute evaluation run."""
    service = EvaluationService()
    try:
        if payload.async_execution:
            from app.models.evaluation import EvaluationStatus
            from app.workers.celery_app import run_evaluation_job
            run = EvaluationRun(
                dataset_id=payload.dataset_id,
                tenant_id=tenant_context.tenant.id,
                retrieval_strategy=payload.retrieval_strategy,
                evaluation_status=EvaluationStatus.PENDING.value,
                configuration={"async": True, "top_k": payload.top_k},
            )
            db.add(run)
            await db.commit()
            await db.refresh(run)
            try:
                run_evaluation_job.delay(str(run.id), str(tenant_context.tenant.id))
            except Exception as ce:
                # If Celery broker is temporarily unavailable, fallback to sync execution
                run = await service.run_evaluation(
                    db=db,
                    tenant_id=tenant_context.tenant.id,
                    dataset_id=payload.dataset_id,
                    retrieval_strategy=payload.retrieval_strategy,
                    top_k=payload.top_k,
                    candidate_top_k=payload.candidate_top_k,
                )
            return RunResponse.model_validate(run)

        run = await service.run_evaluation(
            db=db,
            tenant_id=tenant_context.tenant.id,
            dataset_id=payload.dataset_id,
            retrieval_strategy=payload.retrieval_strategy,
            top_k=payload.top_k,
            candidate_top_k=payload.candidate_top_k,
        )
        return RunResponse.model_validate(run)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.get(
    "/runs",
    response_model=List[RunResponse],
    summary="List Evaluation Runs",
    description="List all benchmark evaluation runs executed within the tenant organization.",
)
async def list_runs(
    dataset_id: Optional[uuid.UUID] = Query(None, description="Optional filter by dataset ID."),
    tenant_context: TenantContext = Depends(get_tenant_context),
    db: AsyncSession = Depends(get_db),
) -> List[RunResponse]:
    """Retrieve evaluation run history."""
    query = select(EvaluationRun).where(EvaluationRun.tenant_id == tenant_context.tenant.id)
    if dataset_id:
        query = query.where(EvaluationRun.dataset_id == dataset_id)
    query = query.order_by(EvaluationRun.created_at.desc())

    res = await db.execute(query)
    runs = res.scalars().all()
    return [RunResponse.model_validate(r) for r in runs]


@router.get(
    "/runs/{run_id}",
    response_model=RunResponse,
    summary="Get Evaluation Run Details",
    description="Retrieve aggregate Ragas metrics, duration, and status of an evaluation run.",
)
async def get_run(
    run_id: uuid.UUID,
    tenant_context: TenantContext = Depends(get_tenant_context),
    db: AsyncSession = Depends(get_db),
) -> RunResponse:
    """Fetch single evaluation run."""
    stmt = select(EvaluationRun).where(
        EvaluationRun.id == run_id,
        EvaluationRun.tenant_id == tenant_context.tenant.id,
    )
    res = await db.execute(stmt)
    run = res.scalar_one_or_none()
    if not run:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Evaluation run not found.")
    return RunResponse.model_validate(run)


@router.get(
    "/runs/{run_id}/results",
    response_model=List[ResultResponse],
    summary="Get Sample Evaluation Results",
    description="Retrieve granular per-sample evaluation scores, generated answers, and retrieved contexts.",
)
async def get_run_results(
    run_id: uuid.UUID,
    tenant_context: TenantContext = Depends(get_tenant_context),
    db: AsyncSession = Depends(get_db),
) -> List[ResultResponse]:
    """Fetch sample-level evaluation results."""
    # Verify run exists and belongs to tenant
    stmt = select(EvaluationRun).where(
        EvaluationRun.id == run_id,
        EvaluationRun.tenant_id == tenant_context.tenant.id,
    )
    res = await db.execute(stmt)
    if not res.scalar_one_or_none():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Evaluation run not found.")

    results_stmt = (
        select(EvaluationResult)
        .where(
            EvaluationResult.run_id == run_id,
            EvaluationResult.tenant_id == tenant_context.tenant.id,
        )
        .order_by(EvaluationResult.created_at)
    )
    res_results = await db.execute(results_stmt)
    results = res_results.scalars().all()
    return [ResultResponse.model_validate(r) for r in results]


@router.get(
    "/compare",
    response_model=StrategyComparisonResponse,
    summary="Compare Retrieval Strategies",
    description="Executes and compares all 4 retrieval strategies (Vector, BM25, Hybrid RRF, Hybrid+Rerank) against a dataset.",
    dependencies=[Depends(evaluation_rate_limiter)],
)
async def compare_retrieval_strategies(
    dataset_id: uuid.UUID = Query(..., description="ID of the evaluation dataset to benchmark."),
    top_k: int = Query(5, ge=1, le=50),
    candidate_top_k: int = Query(20, ge=1, le=100),
    tenant_context: TenantContext = Depends(get_tenant_context),
    db: AsyncSession = Depends(get_db),
) -> StrategyComparisonResponse:
    """Run side-by-side strategy benchmark comparison."""
    service = EvaluationService()
    try:
        report = await service.compare_strategies(
            db=db,
            tenant_id=tenant_context.tenant.id,
            dataset_id=dataset_id,
            top_k=top_k,
            candidate_top_k=candidate_top_k,
        )
        return StrategyComparisonResponse.model_validate(report)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
