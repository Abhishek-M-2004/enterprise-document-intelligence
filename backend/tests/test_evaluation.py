"""Phase 7 automated test suite for Ragas evaluation engine, datasets, and multi-tenancy."""

import json
import pytest
from httpx import AsyncClient
import uuid
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.evaluation import (
    EvaluationDataset,
    EvaluationResult,
    EvaluationRun,
    EvaluationSample,
    EvaluationStatus,
    RetrievalStrategy,
)
from app.services.evaluation_service import EvaluationService


@pytest.mark.asyncio
async def test_dataset_creation_and_input_validation(async_client: AsyncClient, auth_headers: dict):
    """Verify dataset provisioning and input validation constraints."""
    # 1. Reject empty dataset name
    res = await async_client.post(
        "/api/v1/evaluation/datasets",
        json={"name": "", "description": "Invalid"},
        headers=auth_headers,
    )
    assert res.status_code == 422 or res.status_code == 400

    # 2. Successfully create benchmark dataset
    res = await async_client.post(
        "/api/v1/evaluation/datasets",
        json={"name": "Q4 Compliance Benchmark", "description": "Production RAG evaluation", "version": "1.0.0"},
        headers=auth_headers,
    )
    assert res.status_code == 201
    dataset_data = res.json()
    assert dataset_data["name"] == "Q4 Compliance Benchmark"
    assert dataset_data["sample_count"] == 0
    dataset_id = dataset_data["id"]

    # 3. Add valid sample
    sample_res = await async_client.post(
        f"/api/v1/evaluation/datasets/{dataset_id}/samples",
        json={
            "question": "What is the token limit for context builder?",
            "ground_truth": "The context builder limits passage tokens to MAX_CONTEXT_TOKENS (default 3000 tokens).",
            "reference_contexts": ["ContextBuilder enforces a ceiling of 3000 tokens."],
        },
        headers=auth_headers,
    )
    assert sample_res.status_code == 201
    sample_data = sample_res.json()
    assert sample_data["question"] == "What is the token limit for context builder?"
    assert sample_data["ground_truth"] is not None

    # 4. Reject empty question
    bad_sample_res = await async_client.post(
        f"/api/v1/evaluation/datasets/{dataset_id}/samples",
        json={"question": "   "},
        headers=auth_headers,
    )
    assert bad_sample_res.status_code == 422 or bad_sample_res.status_code == 400


@pytest.mark.asyncio
async def test_dataset_json_and_csv_import(async_client: AsyncClient, auth_headers: dict):
    """Verify bulk import of evaluation questions from JSON and CSV files."""
    # 1. Create dataset
    ds_res = await async_client.post(
        "/api/v1/evaluation/datasets",
        json={"name": "Bulk Import Benchmark", "description": "Test imports"},
        headers=auth_headers,
    )
    dataset_id = ds_res.json()["id"]

    # 2. Test JSON Import
    json_payload = json.dumps([
        {
            "question": "How does cross-encoder reranking function?",
            "ground_truth": "BGE Cross-encoder computes joint sequence attention scores across query-chunk pairs.",
            "reference_contexts": ["Cross-encoders evaluate (query, chunk) pairs simultaneously."],
        },
        {
            "question": "What is the default RRF constant?",
            "ground_truth": "The standard RRF constant k is 60.",
            "reference_contexts": ["RRF score = 1 / (60 + rank)."],
        },
    ])
    import_json_res = await async_client.post(
        f"/api/v1/evaluation/datasets/{dataset_id}/import",
        files={"file": ("dataset.json", json_payload.encode("utf-8"), "application/json")},
        headers=auth_headers,
    )
    assert import_json_res.status_code == 200
    assert import_json_res.json()["success_count"] == 2
    assert import_json_res.json()["error_count"] == 0

    # 3. Test CSV Import
    csv_payload = (
        "question,ground_truth,expected_context\n"
        "What encryption is used for passwords?,Argon2id password hashing,Passwords are hashed with Argon2id.\n"
        "How are tenant scopes enforced?,PostgreSQL Row Level Security,RLS isolates rows by tenant_id.\n"
    )
    import_csv_res = await async_client.post(
        f"/api/v1/evaluation/datasets/{dataset_id}/import",
        files={"file": ("dataset.csv", csv_payload.encode("utf-8"), "text/csv")},
        headers=auth_headers,
    )
    assert import_csv_res.status_code == 200
    assert import_csv_res.json()["success_count"] == 2

    # 4. Verify total samples in dataset
    samples_res = await async_client.get(
        f"/api/v1/evaluation/datasets/{dataset_id}/samples",
        headers=auth_headers,
    )
    assert samples_res.status_code == 200
    assert len(samples_res.json()) == 4


@pytest.mark.asyncio
async def test_missing_ground_truth_handling():
    """Verify that omitting ground_truth does not silently invent scores for reference metrics."""
    service = EvaluationService()

    # When ground_truth is provided
    metrics_with_gt = service._compute_deterministic_metrics(
        question="What is the capital of France?",
        generated_answer="The capital of France is Paris.",
        retrieved_contexts=["Paris is the capital of France."],
        ground_truth="Paris is France's capital city.",
    )
    assert metrics_with_gt["faithfulness"] is not None
    assert metrics_with_gt["answer_relevancy"] is not None
    assert metrics_with_gt["context_recall"] is not None
    assert metrics_with_gt["context_precision"] is not None
    assert metrics_with_gt["answer_correctness"] is not None

    # When ground_truth is omitted (None or empty)
    metrics_without_gt = service._compute_deterministic_metrics(
        question="What is the capital of France?",
        generated_answer="The capital of France is Paris.",
        retrieved_contexts=["Paris is the capital of France."],
        ground_truth=None,
    )
    assert metrics_without_gt["faithfulness"] is not None
    assert metrics_without_gt["answer_relevancy"] is not None
    # Must NOT silently fabricate ground-truth dependent metrics
    assert metrics_without_gt["context_recall"] is None
    assert metrics_without_gt["context_precision"] is None
    assert metrics_without_gt["answer_correctness"] is None


@pytest.mark.asyncio
async def test_synthetic_dataset_and_evaluation_run_lifecycle(
    async_client: AsyncClient,
    auth_headers: dict,
):
    """Verify end-to-end evaluation run lifecycle, score calculation, and result persistence."""
    # 1. Create synthetic dataset
    ds_res = await async_client.post(
        "/api/v1/evaluation/datasets/synthetic",
        headers=auth_headers,
    )
    assert ds_res.status_code == 201
    dataset = ds_res.json()
    dataset_id = dataset["id"]
    assert dataset["sample_count"] == 3

    # 2. Launch Hybrid+Reranker Evaluation Run
    run_res = await async_client.post(
        "/api/v1/evaluation/runs",
        json={
            "dataset_id": dataset_id,
            "retrieval_strategy": "hybrid_rerank",
            "top_k": 3,
            "candidate_top_k": 10,
            "async_execution": False,
        },
        headers=auth_headers,
    )
    assert run_res.status_code == 201
    run_data = run_res.json()
    assert run_data["evaluation_status"] == "COMPLETED"
    assert run_data["total_samples"] == 3
    assert run_data["completed_samples"] == 3
    run_id = run_data["id"]

    # Verify aggregate metrics
    agg = run_data["aggregate_metrics"]
    assert "faithfulness" in agg
    assert "answer_relevancy" in agg
    assert "mean_latency_ms" in agg

    # 3. Retrieve per-sample results
    results_res = await async_client.get(
        f"/api/v1/evaluation/runs/{run_id}/results",
        headers=auth_headers,
    )
    assert results_res.status_code == 200
    results = results_res.json()
    assert len(results) == 3
    for r in results:
        assert r["run_id"] == run_id
        assert isinstance(r["latency_ms"], (int, float))
        assert "generated_answer" in r


@pytest.mark.asyncio
async def test_retrieval_strategy_comparison(
    async_client: AsyncClient,
    auth_headers: dict,
):
    """Verify strategy benchmark comparison evaluates all 4 configurations on the exact same dataset."""
    # 1. Create synthetic dataset
    ds_res = await async_client.post(
        "/api/v1/evaluation/datasets/synthetic?name=Comparison%20Benchmark",
        headers=auth_headers,
    )
    dataset_id = ds_res.json()["id"]

    # 2. Run strategy comparison
    comp_res = await async_client.get(
        f"/api/v1/evaluation/compare?dataset_id={dataset_id}&top_k=3&candidate_top_k=10",
        headers=auth_headers,
    )
    assert comp_res.status_code == 200
    comp_data = comp_res.json()

    # Must contain all 4 retrieval strategies
    expected_strategies = ["vector", "bm25", "hybrid_rrf", "hybrid_rerank"]
    assert set(comp_data["strategies_evaluated"]) == set(expected_strategies)
    assert len(comp_data["comparison"]) == 4

    for item in comp_data["comparison"]:
        assert item["status"] == "COMPLETED"
        assert item["total_samples"] == 3
        assert "mean_latency_ms" in item["metrics"]


@pytest.mark.asyncio
async def test_evaluation_multi_tenant_isolation(
    async_client: AsyncClient,
    auth_headers: dict,
    db_session: AsyncSession,
):
    """Verify that Tenant B cannot access, read, or modify Tenant A's evaluation datasets or runs."""
    # 1. Create dataset under Tenant A
    ds_res = await async_client.post(
        "/api/v1/evaluation/datasets",
        json={"name": "Tenant A Secret Dataset"},
        headers=auth_headers,
    )
    dataset_id = ds_res.json()["id"]

    # 2. Register Tenant B
    tenant_b_email = f"tenant_b_{uuid.uuid4().hex[:6]}@enterprise.com"
    reg_b = await async_client.post(
        "/api/v1/auth/register",
        json={
            "email": tenant_b_email,
            "password": "SecurePassword123!",
            "full_name": "Tenant B Admin",
            "organization_name": "Tenant B Corp",
        },
    )
    token_b = reg_b.json()["access_token"]
    tenant_b_id = reg_b.json()["organization"]["id"]
    headers_b = {
        "Authorization": f"Bearer {token_b}",
        "X-Tenant-ID": tenant_b_id,
    }

    # 3. Tenant B attempts to fetch Tenant A's dataset -> HTTP 404
    get_res = await async_client.get(
        f"/api/v1/evaluation/datasets/{dataset_id}",
        headers=headers_b,
    )
    assert get_res.status_code == 404

    # 4. Tenant B attempts to add samples to Tenant A's dataset -> HTTP 400 or 404
    add_res = await async_client.post(
        f"/api/v1/evaluation/datasets/{dataset_id}/samples",
        json={"question": "Unauthorized access test?"},
        headers=headers_b,
    )
    assert add_res.status_code in [400, 404]

    # 5. Verify direct PostgreSQL Row-Level Security blocks cross-tenant reads
    await db_session.execute(text("GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO rls_app_user"))
    await db_session.execute(text("SET LOCAL ROLE rls_app_user"))
    await db_session.execute(
        text("SELECT set_config('app.current_tenant_id', :tid, true)"),
        {"tid": str(tenant_b_id)},
    )
    rls_check = await db_session.execute(
        text("SELECT count(*) FROM evaluation_datasets WHERE id = :did"),
        {"did": dataset_id},
    )
    assert rls_check.scalar_one() == 0
