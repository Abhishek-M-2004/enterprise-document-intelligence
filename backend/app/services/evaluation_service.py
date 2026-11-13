"""Ragas RAG Evaluation and Benchmarking Engine with multi-strategy comparison."""

import csv
import io
import json
import logging
import math
import re
import time
from typing import Any, Dict, List, Optional, Tuple
import uuid
from datetime import datetime, timezone
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.core.metrics import record_evaluation_run
from app.core.tracing import trace_span
from app.models.evaluation import (
    EvaluationDataset,
    EvaluationResult,
    EvaluationRun,
    EvaluationSample,
    EvaluationStatus,
    RetrievalStrategy,
)
from app.services.context_builder import ContextBuilder
from app.services.embedding_service import EmbeddingService
from app.services.llm_service import LLMService
from app.services.retrieval_service import RetrievalService

logger = logging.getLogger("app.evaluation")


class EvaluationService:
    """Service orchestrating Ragas evaluations, dataset imports, and multi-strategy benchmarks."""

    def __init__(self):
        self.retrieval_service = RetrievalService()
        self.llm_service = LLMService.get_instance()
        self.embedding_service = EmbeddingService.get_instance()

    # --------------------------------------------------------------------------
    # Dataset Management & Parsing
    # --------------------------------------------------------------------------

    async def create_dataset(
        self,
        db: AsyncSession,
        tenant_id: uuid.UUID,
        name: str,
        description: Optional[str] = None,
        version: str = "1.0.0",
    ) -> EvaluationDataset:
        """Create a new tenant-isolated evaluation dataset."""
        if not name or not name.strip():
            raise ValueError("Dataset name cannot be empty.")

        dataset = EvaluationDataset(
            tenant_id=tenant_id,
            name=name.strip(),
            description=description.strip() if description else None,
            version=version.strip() if version else "1.0.0",
        )
        db.add(dataset)
        await db.commit()
        await db.refresh(dataset)
        return dataset

    async def add_sample(
        self,
        db: AsyncSession,
        tenant_id: uuid.UUID,
        dataset_id: uuid.UUID,
        question: str,
        ground_truth: Optional[str] = None,
        reference_contexts: Optional[List[str]] = None,
        relevant_document_ids: Optional[List[str]] = None,
        sample_metadata: Optional[Dict[str, Any]] = None,
    ) -> EvaluationSample:
        """Add an evaluation sample record with strict input validation."""
        if not question or not question.strip():
            raise ValueError("Evaluation question cannot be empty.")

        # Verify dataset exists and belongs to tenant
        stmt = select(EvaluationDataset).where(
            EvaluationDataset.id == dataset_id,
            EvaluationDataset.tenant_id == tenant_id,
        )
        res = await db.execute(stmt)
        dataset = res.scalar_one_or_none()
        if not dataset:
            raise ValueError("Evaluation dataset not found or unauthorized.")

        sample = EvaluationSample(
            dataset_id=dataset_id,
            tenant_id=tenant_id,
            question=question.strip(),
            ground_truth=ground_truth.strip() if ground_truth else None,
            reference_contexts=reference_contexts or [],
            relevant_document_ids=relevant_document_ids or [],
            sample_metadata=sample_metadata or {},
        )
        db.add(sample)
        await db.commit()
        await db.refresh(sample)
        return sample

    async def update_sample(
        self,
        db: AsyncSession,
        tenant_id: uuid.UUID,
        sample_id: uuid.UUID,
        ground_truth: Optional[str] = None,
        reference_contexts: Optional[List[str]] = None,
        sample_metadata: Optional[Dict[str, Any]] = None,
    ) -> EvaluationSample:
        """Human review & correction mechanism for reference answers and ground truth."""
        stmt = select(EvaluationSample).where(
            EvaluationSample.id == sample_id,
            EvaluationSample.tenant_id == tenant_id,
        )
        res = await db.execute(stmt)
        sample = res.scalar_one_or_none()
        if not sample:
            raise ValueError("Evaluation sample not found or unauthorized.")

        if ground_truth is not None:
            sample.ground_truth = ground_truth.strip() if ground_truth else None
        if reference_contexts is not None:
            sample.reference_contexts = reference_contexts
        if sample_metadata is not None:
            sample.sample_metadata = sample_metadata

        await db.commit()
        await db.refresh(sample)
        return sample

    async def import_samples_from_json(
        self,
        db: AsyncSession,
        tenant_id: uuid.UUID,
        dataset_id: uuid.UUID,
        json_content: str,
    ) -> Tuple[int, List[str]]:
        """Parse, validate, and persist evaluation samples from JSON text."""
        try:
            records = json.loads(json_content)
        except json.JSONDecodeError as e:
            raise ValueError(f"Malformed JSON dataset payload: {e}")

        if not isinstance(records, list):
            raise ValueError("JSON dataset must contain a top-level list of sample objects.")

        success_count = 0
        errors: List[str] = []

        for idx, rec in enumerate(records):
            if not isinstance(rec, dict):
                errors.append(f"Row {idx}: Item is not a valid JSON dictionary.")
                continue

            question = rec.get("question")
            if not question or not str(question).strip():
                errors.append(f"Row {idx}: Missing mandatory 'question' field.")
                continue

            ground_truth = rec.get("ground_truth") or rec.get("reference")
            ref_ctx = rec.get("reference_contexts") or rec.get("expected_context") or []
            if isinstance(ref_ctx, str):
                ref_ctx = [ref_ctx]
            doc_ids = rec.get("relevant_document_ids") or []
            meta = rec.get("metadata") or {}

            sample = EvaluationSample(
                dataset_id=dataset_id,
                tenant_id=tenant_id,
                question=str(question).strip(),
                ground_truth=str(ground_truth).strip() if ground_truth else None,
                reference_contexts=ref_ctx if isinstance(ref_ctx, list) else [],
                relevant_document_ids=doc_ids if isinstance(doc_ids, list) else [],
                sample_metadata=meta if isinstance(meta, dict) else {},
            )
            db.add(sample)
            success_count += 1

        if success_count > 0:
            await db.commit()

        return success_count, errors

    async def import_samples_from_csv(
        self,
        db: AsyncSession,
        tenant_id: uuid.UUID,
        dataset_id: uuid.UUID,
        csv_content: str,
    ) -> Tuple[int, List[str]]:
        """Parse, validate, and persist evaluation samples from CSV text."""
        reader = csv.DictReader(io.StringIO(csv_content))
        if not reader.fieldnames or "question" not in [f.strip().lower() for f in reader.fieldnames]:
            raise ValueError("CSV dataset must contain a header with at least a 'question' column.")

        success_count = 0
        errors: List[str] = []

        for row_idx, row in enumerate(reader, start=1):
            normalized_row = {k.strip().lower(): v for k, v in row.items() if k}
            question = normalized_row.get("question")
            if not question or not question.strip():
                errors.append(f"Row {row_idx}: Empty or missing 'question'.")
                continue

            ground_truth = normalized_row.get("ground_truth") or normalized_row.get("reference")
            ref_ctx_raw = normalized_row.get("reference_contexts") or normalized_row.get("expected_context") or ""
            ref_ctx = [c.strip() for c in ref_ctx_raw.split("||") if c.strip()] if ref_ctx_raw else []

            sample = EvaluationSample(
                dataset_id=dataset_id,
                tenant_id=tenant_id,
                question=question.strip(),
                ground_truth=ground_truth.strip() if ground_truth else None,
                reference_contexts=ref_ctx,
                relevant_document_ids=[],
                sample_metadata={"import_source": "csv", "row_index": row_idx},
            )
            db.add(sample)
            success_count += 1

        if success_count > 0:
            await db.commit()

        return success_count, errors

    async def create_synthetic_dataset(
        self,
        db: AsyncSession,
        tenant_id: uuid.UUID,
        name: str = "Synthetic Development Benchmark",
    ) -> EvaluationDataset:
        """Create a standard synthetic baseline dataset for local evaluation and regression testing."""
        dataset = await self.create_dataset(
            db=db,
            tenant_id=tenant_id,
            name=name,
            description="Built-in benchmark dataset with verified reference answers for automated quality evaluation.",
            version="1.0.0",
        )

        synthetic_samples = [
            {
                "question": "What is the primary architectural design pattern of this platform?",
                "ground_truth": "The platform implements a multi-tenant Enterprise Document Intelligence Architecture with isolated vector storage, hybrid search, cross-encoder reranking, and conversational RAG.",
                "reference_contexts": [
                    "Multi-tenant Enterprise Document Intelligence Architecture with PostgreSQL RLS, Qdrant vectors, BM25, and BGE Cross-Encoder."
                ],
            },
            {
                "question": "How does the platform prevent cross-tenant data leakage?",
                "ground_truth": "Cross-tenant leakage is strictly prevented via PostgreSQL Row-Level Security (RLS) policies enforcing app.current_tenant_id, tenant-isolated Qdrant payload filters, and per-tenant BM25 indexes.",
                "reference_contexts": [
                    "PostgreSQL Row-Level Security (RLS) session variable app.current_tenant_id enforces tenant isolation on all tables. Qdrant searches apply strict tenant_id payload filtering."
                ],
            },
            {
                "question": "What retrieval techniques are combined in hybrid search?",
                "ground_truth": "Hybrid search combines dense vector cosine similarity via Qdrant and lexical BM25 Okapi search using Reciprocal Rank Fusion (RRF) with constant k=60.",
                "reference_contexts": [
                    "Reciprocal Rank Fusion merges dense vector search candidates and BM25 Okapi lexical candidates with formula 1 / (60 + rank)."
                ],
            },
        ]

        for s in synthetic_samples:
            await self.add_sample(
                db=db,
                tenant_id=tenant_id,
                dataset_id=dataset.id,
                question=s["question"],
                ground_truth=s["ground_truth"],
                reference_contexts=s["reference_contexts"],
                sample_metadata={"synthetic": True},
            )

        return dataset

    # --------------------------------------------------------------------------
    # Ragas Metric Computation Engine
    # --------------------------------------------------------------------------

    def _compute_deterministic_metrics(
        self,
        question: str,
        generated_answer: str,
        retrieved_contexts: List[str],
        ground_truth: Optional[str] = None,
        reference_contexts: Optional[List[str]] = None,
    ) -> Dict[str, Optional[float]]:
        """Compute mathematically rigorous evaluation metrics without relying on third-party API dependencies.

        - Context Recall: Overlap ratio of ground-truth informative terms found in retrieved passages.
        - Context Precision: Weighted precision score prioritizing presence of relevant terms in higher ranked passages.
        - Faithfulness: Ratio of answer claim terms grounded in retrieved contexts (anti-hallucination metric).
        - Answer Relevancy: Lexical and semantic term overlap between question and generated response.
        - Answer Correctness: F1 token overlap and factual alignment between generated answer and ground truth.
        """
        def tokenize(text: str) -> set[str]:
            tokens = re.findall(r"\b\w{3,}\b", text.lower())
            stop_words = {"the", "and", "for", "with", "that", "this", "from", "are", "was", "were", "been", "have", "has"}
            return {t for t in tokens if t not in stop_words}

        q_tokens = tokenize(question)
        ans_tokens = tokenize(generated_answer)
        ctx_tokens = set()
        for c in retrieved_contexts:
            ctx_tokens.update(tokenize(c))

        # 1. Faithfulness (Groundedness in context: ans_tokens in ctx_tokens)
        if ans_tokens:
            grounded_tokens = ans_tokens.intersection(ctx_tokens)
            faithfulness = round(len(grounded_tokens) / len(ans_tokens), 4)
        else:
            faithfulness = 1.0 if not generated_answer.strip() else 0.0

        # 2. Answer Relevancy (Question alignment: q_tokens in ans_tokens)
        if q_tokens:
            relevancy_tokens = q_tokens.intersection(ans_tokens)
            answer_relevancy = round(min(1.0, len(relevancy_tokens) / len(q_tokens) * 1.2), 4)
        else:
            answer_relevancy = 0.5

        # 3. Reference-dependent metrics (Require ground_truth)
        context_recall: Optional[float] = None
        context_precision: Optional[float] = None
        answer_correctness: Optional[float] = None

        if ground_truth and ground_truth.strip():
            gt_tokens = tokenize(ground_truth)
            if gt_tokens:
                # Context Recall: fraction of ground-truth tokens retrieved
                recalled_tokens = gt_tokens.intersection(ctx_tokens)
                context_recall = round(len(recalled_tokens) / len(gt_tokens), 4)

                # Context Precision: Rank-weighted precision over retrieved contexts
                if retrieved_contexts:
                    precisions = []
                    for rank, ctx in enumerate(retrieved_contexts, start=1):
                        c_tokens = tokenize(ctx)
                        hit_ratio = len(c_tokens.intersection(gt_tokens)) / max(1, len(c_tokens))
                        precisions.append(hit_ratio / rank)
                    context_precision = round(min(1.0, sum(precisions) * 2.0), 4)
                else:
                    context_precision = 0.0

                # Answer Correctness: Token F1 overlap with ground truth
                overlap = len(ans_tokens.intersection(gt_tokens))
                precision = overlap / max(1, len(ans_tokens))
                recall = overlap / max(1, len(gt_tokens))
                f1 = (2 * precision * recall) / max(0.0001, precision + recall)
                answer_correctness = round(min(1.0, f1), 4)

        return {
            "faithfulness": faithfulness,
            "answer_relevancy": answer_relevancy,
            "context_precision": context_precision,
            "context_recall": context_recall,
            "answer_correctness": answer_correctness,
        }

    async def _evaluate_with_ragas(
        self,
        samples_data: List[Dict[str, Any]],
    ) -> Tuple[str, List[Dict[str, Optional[float]]]]:
        """Execute Ragas evaluation library against collected samples when live evaluator credentials are available.

        Returns (evaluator_type, computed_metrics) where evaluator_type is 'ragas' or 'deterministic'.
        """
        has_openai = bool(settings.OPENAI_API_KEY and not settings.OPENAI_API_KEY.startswith("your_"))
        if not has_openai:
            logger.info("No live evaluator OpenAI API key configured. Executing deterministic evaluation engine.")
            return "deterministic", [
                self._compute_deterministic_metrics(
                    question=s["question"],
                    generated_answer=s["generated_answer"],
                    retrieved_contexts=s["retrieved_contexts"],
                    ground_truth=s.get("ground_truth"),
                    reference_contexts=s.get("reference_contexts"),
                )
                for s in samples_data
            ]

        try:
            from ragas import evaluate
            from ragas.dataset_schema import EvaluationDataset as RagasEvaluationDataset, SingleTurnSample
            from ragas.metrics.collections import (
                answer_correctness,
                answer_relevancy,
                context_precision,
                context_recall,
                faithfulness,
            )

            ragas_samples = []
            for s in samples_data:
                ragas_samples.append(
                    SingleTurnSample(
                        user_input=s["question"],
                        response=s["generated_answer"],
                        retrieved_contexts=s["retrieved_contexts"],
                        reference=s.get("ground_truth") or "",
                        reference_contexts=s.get("reference_contexts") or [],
                    )
                )

            dataset = RagasEvaluationDataset(samples=ragas_samples)
            metrics = [faithfulness, answer_relevancy, context_precision, context_recall, answer_correctness]

            ragas_res = evaluate(dataset=dataset, metrics=metrics, show_progress=False)
            df = ragas_res.to_pandas()

            results = []
            for idx, (_, row) in enumerate(df.iterrows()):
                s = samples_data[idx]
                has_gt = bool(s.get("ground_truth") and str(s.get("ground_truth")).strip())
                results.append({
                    "faithfulness": float(row.get("faithfulness")) if not math.isnan(row.get("faithfulness", float("nan"))) else None,
                    "answer_relevancy": float(row.get("answer_relevancy")) if not math.isnan(row.get("answer_relevancy", float("nan"))) else None,
                    "context_precision": (float(row.get("context_precision")) if not math.isnan(row.get("context_precision", float("nan"))) else None) if has_gt else None,
                    "context_recall": (float(row.get("context_recall")) if not math.isnan(row.get("context_recall", float("nan"))) else None) if has_gt else None,
                    "answer_correctness": (float(row.get("answer_correctness")) if not math.isnan(row.get("answer_correctness", float("nan"))) else None) if has_gt else None,
                })
            return "ragas", results

        except Exception as e:
            logger.warning(f"Ragas evaluation invocation failed ({e}). Falling back to deterministic metrics.")
            return "deterministic", [
                self._compute_deterministic_metrics(
                    question=s["question"],
                    generated_answer=s["generated_answer"],
                    retrieved_contexts=s["retrieved_contexts"],
                    ground_truth=s.get("ground_truth"),
                    reference_contexts=s.get("reference_contexts"),
                )
                for s in samples_data
            ]

    # --------------------------------------------------------------------------
    # Evaluation Execution Pipeline
    # --------------------------------------------------------------------------

    async def run_evaluation(
        self,
        db: AsyncSession,
        tenant_id: uuid.UUID,
        dataset_id: uuid.UUID,
        retrieval_strategy: str = RetrievalStrategy.HYBRID_RERANK.value,
        top_k: int = 5,
        candidate_top_k: int = 20,
    ) -> EvaluationRun:
        """Execute benchmark evaluation across all dataset samples for the chosen retrieval strategy."""
        with trace_span(f"EvaluationRun.{retrieval_strategy}", {"tenant_id": str(tenant_id), "strategy": retrieval_strategy}):
            # 1. Fetch dataset and its samples
            stmt = (
                select(EvaluationDataset)
                .options(selectinload(EvaluationDataset.samples))
                .where(
                    EvaluationDataset.id == dataset_id,
                    EvaluationDataset.tenant_id == tenant_id,
                )
            )
            res = await db.execute(stmt)
            dataset = res.scalar_one_or_none()
            if not dataset:
                raise ValueError("Evaluation dataset not found or unauthorized.")

            if not dataset.samples:
                raise ValueError("Cannot evaluate an empty dataset. Add evaluation samples first.")

            # 2. Initialize EvaluationRun record
            run = EvaluationRun(
                dataset_id=dataset_id,
                tenant_id=tenant_id,
                retrieval_strategy=retrieval_strategy,
                evaluation_status=EvaluationStatus.RUNNING.value,
                total_samples=len(dataset.samples),
                completed_samples=0,
                configuration={
                    "retrieval_strategy": retrieval_strategy,
                    "top_k": top_k,
                    "candidate_top_k": candidate_top_k,
                    "llm_provider": settings.LLM_PROVIDER,
                    "evaluator_type": "ragas" if (settings.OPENAI_API_KEY and not settings.OPENAI_API_KEY.startswith("your_")) else "deterministic",
                },
            )
            db.add(run)
            await db.commit()
            await db.refresh(run)

            samples_intermediate = []
            collected_results = []
            start_run_time = time.perf_counter()

            try:
                # 3. Execute retrieval and answer generation for each sample
                for sample in dataset.samples:
                    sample_t0 = time.perf_counter()
                    retrieved_chunks: List[Dict[str, Any]] = []

                    # Execute selected retrieval strategy
                    if retrieval_strategy == RetrievalStrategy.VECTOR_ONLY.value:
                        ret_res = await self.retrieval_service.vector_search(
                            db=db,
                            tenant_id=tenant_id,
                            query=sample.question,
                            top_k=top_k,
                        )
                        retrieved_chunks = ret_res.get("results", [])

                    elif retrieval_strategy == RetrievalStrategy.BM25_ONLY.value:
                        ret_res = await self.retrieval_service.bm25_search(
                            db=db,
                            tenant_id=tenant_id,
                            query=sample.question,
                            top_k=top_k,
                        )
                        retrieved_chunks = ret_res.get("results", [])

                    elif retrieval_strategy == RetrievalStrategy.HYBRID_RRF.value:
                        ret_res = await self.retrieval_service.hybrid_search(
                            db=db,
                            tenant_id=tenant_id,
                            query=sample.question,
                            top_k=top_k,
                            rerank=False,
                        )
                        retrieved_chunks = ret_res.get("results", [])

                    else:  # HYBRID_RERANK
                        ret_res = await self.retrieval_service.hybrid_search_with_reranking(
                            db=db,
                            tenant_id=tenant_id,
                            query=sample.question,
                            top_k=top_k,
                            candidate_top_k=candidate_top_k,
                        )
                        retrieved_chunks = ret_res.get("results", [])

                    retrieved_contexts = [c.get("content", "") for c in retrieved_chunks if c.get("content")]

                    # Build context and prompt LLM
                    if retrieved_chunks:
                        built_ctx = ContextBuilder.build_context(retrieved_chunks)
                        context_str = built_ctx.context_text
                        system_prompt = (
                            "You are a helpful assistant. Answer the user question based strictly on the provided context passages.\n\n"
                            f"Context:\n{context_str}"
                        )
                        messages = [
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": sample.question},
                        ]
                        llm_out = await self.llm_service.generate_answer(messages=messages, temperature=0.1)
                        generated_answer = llm_out.get("content", "")
                    else:
                        generated_answer = "I could not find any relevant information in the uploaded documents to answer this question."

                    sample_latency_ms = round((time.perf_counter() - sample_t0) * 1000, 2)

                    samples_intermediate.append({
                        "sample_id": sample.id,
                        "question": sample.question,
                        "generated_answer": generated_answer,
                        "retrieved_contexts": retrieved_contexts,
                        "ground_truth": sample.ground_truth,
                        "reference_contexts": sample.reference_contexts,
                        "latency_ms": sample_latency_ms,
                    })

                # 4. Compute Ragas evaluation metrics (or deterministic fallback)
                actual_evaluator_type, computed_metrics = await self._evaluate_with_ragas(samples_intermediate)

                # Update run configuration with the actual evaluator utilized
                updated_config = dict(run.configuration or {})
                updated_config["evaluator_type"] = actual_evaluator_type
                run.configuration = updated_config

                # 5. Persist per-sample EvaluationResult records
                for sample_data, metrics in zip(samples_intermediate, computed_metrics):
                    eval_result = EvaluationResult(
                        run_id=run.id,
                        sample_id=sample_data["sample_id"],
                        tenant_id=tenant_id,
                        generated_answer=sample_data["generated_answer"],
                        retrieved_contexts=sample_data["retrieved_contexts"],
                        faithfulness=metrics.get("faithfulness"),
                        answer_relevancy=metrics.get("answer_relevancy"),
                        context_precision=metrics.get("context_precision"),
                        context_recall=metrics.get("context_recall"),
                        answer_correctness=metrics.get("answer_correctness"),
                        latency_ms=sample_data["latency_ms"],
                    )
                    db.add(eval_result)
                    collected_results.append(eval_result)

                # 6. Compute aggregate run metrics
                def mean_metric(key: str) -> Optional[float]:
                    vals = [m[key] for m in computed_metrics if m.get(key) is not None]
                    return round(sum(vals) / len(vals), 4) if vals else None

                aggregate = {
                    "faithfulness": mean_metric("faithfulness"),
                    "answer_relevancy": mean_metric("answer_relevancy"),
                    "context_precision": mean_metric("context_precision"),
                    "context_recall": mean_metric("context_recall"),
                    "answer_correctness": mean_metric("answer_correctness"),
                    "mean_latency_ms": round(sum(s["latency_ms"] for s in samples_intermediate) / max(1, len(samples_intermediate)), 2),
                    "total_run_duration_s": round(time.perf_counter() - start_run_time, 2),
                    "evaluator_type": actual_evaluator_type,
                }

                run.evaluation_status = EvaluationStatus.COMPLETED.value
                run.completed_samples = len(dataset.samples)
                run.completed_at = datetime.now(timezone.utc)
                run.aggregate_metrics = aggregate
                await db.commit()
                await db.refresh(run)

                record_evaluation_run(
                    strategy=retrieval_strategy,
                    status="COMPLETED",
                    metrics=aggregate,
                )

                return run

            except Exception as exc:
                logger.error(f"Evaluation run {run.id} failed: {exc}", exc_info=True)
                run.evaluation_status = EvaluationStatus.FAILED.value
                run.error_message = str(exc)[:1000]
                run.completed_at = datetime.now(timezone.utc)
                await db.commit()
                record_evaluation_run(strategy=retrieval_strategy, status="FAILED")
                raise exc

    # --------------------------------------------------------------------------
    # Retrieval Strategy Comparison
    # --------------------------------------------------------------------------

    async def compare_strategies(
        self,
        db: AsyncSession,
        tenant_id: uuid.UUID,
        dataset_id: uuid.UUID,
        top_k: int = 5,
        candidate_top_k: int = 20,
    ) -> Dict[str, Any]:
        """Run all four retrieval strategies against the exact same evaluation dataset and compile comparative analysis."""
        strategies = [
            RetrievalStrategy.VECTOR_ONLY.value,
            RetrievalStrategy.BM25_ONLY.value,
            RetrievalStrategy.HYBRID_RRF.value,
            RetrievalStrategy.HYBRID_RERANK.value,
        ]

        runs_summary = []
        for strat in strategies:
            run = await self.run_evaluation(
                db=db,
                tenant_id=tenant_id,
                dataset_id=dataset_id,
                retrieval_strategy=strat,
                top_k=top_k,
                candidate_top_k=candidate_top_k,
            )
            runs_summary.append({
                "run_id": str(run.id),
                "retrieval_strategy": strat,
                "status": run.evaluation_status,
                "total_samples": run.total_samples,
                "metrics": run.aggregate_metrics,
            })

        return {
            "dataset_id": str(dataset_id),
            "strategies_evaluated": strategies,
            "comparison": runs_summary,
            "timestamp": time.time(),
        }
