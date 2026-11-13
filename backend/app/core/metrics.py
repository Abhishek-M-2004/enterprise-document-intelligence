"""Prometheus metrics instrumentation for enterprise observability."""

from typing import Optional
from prometheus_client import (
    CollectorRegistry,
    Counter,
    Gauge,
    Histogram,
    REGISTRY,
    generate_latest,
)

# Shared platform Prometheus registry
registry: CollectorRegistry = REGISTRY

# 1. API Request & Error Metrics
API_REQUESTS_TOTAL = Counter(
    "rag_api_requests_total",
    "Total count of incoming HTTP requests processed by endpoint and status.",
    ["endpoint", "method", "status_code"],
    registry=registry,
)

API_REQUEST_DURATION_SECONDS = Histogram(
    "rag_api_request_duration_seconds",
    "End-to-end HTTP request processing latency in seconds.",
    ["endpoint", "method"],
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0),
    registry=registry,
)

API_ERRORS_TOTAL = Counter(
    "rag_api_errors_total",
    "Total count of unhandled or 5xx application errors by endpoint.",
    ["endpoint", "error_type"],
    registry=registry,
)

# 2. Document Ingestion Metrics
DOCUMENTS_UPLOADED_TOTAL = Counter(
    "rag_documents_uploaded_total",
    "Total number of PDF documents uploaded across tenants.",
    registry=registry,
)

DOCUMENT_PROCESSING_FAILURES_TOTAL = Counter(
    "rag_document_processing_failures_total",
    "Total number of document background extraction and ingestion failures.",
    registry=registry,
)

# 3. Retrieval & Ranking Latency Metrics
VECTOR_SEARCH_LATENCY_SECONDS = Histogram(
    "rag_vector_search_latency_seconds",
    "Duration of Qdrant dense vector similarity queries in seconds.",
    buckets=(0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0),
    registry=registry,
)

BM25_SEARCH_LATENCY_SECONDS = Histogram(
    "rag_bm25_search_latency_seconds",
    "Duration of BM25 inverted index keyword search in seconds.",
    buckets=(0.0005, 0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25),
    registry=registry,
)

RERANKER_LATENCY_SECONDS = Histogram(
    "rag_reranker_latency_seconds",
    "Duration of BGE Cross-Encoder reranking neural inference in seconds.",
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.0),
    registry=registry,
)

# 4. LLM Generation & Token Metrics
LLM_REQUESTS_TOTAL = Counter(
    "rag_llm_requests_total",
    "Total number of LLM inference queries dispatched by provider and model.",
    ["provider", "model"],
    registry=registry,
)

LLM_REQUEST_DURATION_SECONDS = Histogram(
    "rag_llm_request_duration_seconds",
    "Inference latency of LLM responses in seconds.",
    ["provider", "model"],
    buckets=(0.05, 0.1, 0.25, 0.5, 1.0, 2.0, 5.0, 10.0, 20.0),
    registry=registry,
)

LLM_TOKENS_TOTAL = Counter(
    "rag_llm_tokens_total",
    "Total number of tokens consumed by category, provider, and model.",
    ["type", "provider", "model"],  # type: "prompt" | "completion"
    registry=registry,
)

LLM_ERRORS_TOTAL = Counter(
    "rag_llm_errors_total",
    "Total number of LLM communication or timeout errors.",
    ["provider", "error_type"],
    registry=registry,
)

# 5. RAG Evaluation Metrics
EVALUATION_RUNS_TOTAL = Counter(
    "rag_evaluation_runs_total",
    "Total number of benchmark evaluation runs executed by strategy and status.",
    ["strategy", "status"],
    registry=registry,
)

EVALUATION_METRIC_SCORES = Gauge(
    "rag_evaluation_metric_scores",
    "Latest aggregate Ragas quality scores by metric and retrieval strategy.",
    ["metric", "strategy"],
    registry=registry,
)

ACTIVE_EVALUATION_RUNS = Gauge(
    "rag_active_evaluation_runs",
    "Number of currently running RAG evaluation benchmarks.",
    registry=registry,
)


def record_api_request(endpoint: str, method: str, status_code: int, duration_s: float) -> None:
    """Record an API request occurrence and duration."""
    API_REQUESTS_TOTAL.labels(endpoint=endpoint, method=method, status_code=str(status_code)).inc()
    API_REQUEST_DURATION_SECONDS.labels(endpoint=endpoint, method=method).observe(duration_s)


def record_api_error(endpoint: str, error_type: str) -> None:
    """Record an API error occurrence."""
    API_ERRORS_TOTAL.labels(endpoint=endpoint, error_type=error_type).inc()


def record_retrieval_latencies(
    vector_s: Optional[float] = None,
    bm25_s: Optional[float] = None,
    rerank_s: Optional[float] = None,
) -> None:
    """Record latencies for retrieval components."""
    if vector_s is not None:
        VECTOR_SEARCH_LATENCY_SECONDS.observe(vector_s)
    if bm25_s is not None:
        BM25_SEARCH_LATENCY_SECONDS.observe(bm25_s)
    if rerank_s is not None:
        RERANKER_LATENCY_SECONDS.observe(rerank_s)


def record_llm_metrics(
    provider: str,
    model: str,
    duration_s: float,
    prompt_tokens: int = 0,
    completion_tokens: int = 0,
    error_type: Optional[str] = None,
) -> None:
    """Record LLM generation metrics including latency and token accounting."""
    if error_type:
        LLM_ERRORS_TOTAL.labels(provider=provider, error_type=error_type).inc()
        return

    LLM_REQUESTS_TOTAL.labels(provider=provider, model=model).inc()
    LLM_REQUEST_DURATION_SECONDS.labels(provider=provider, model=model).observe(duration_s)
    if prompt_tokens > 0:
        LLM_TOKENS_TOTAL.labels(type="prompt", provider=provider, model=model).inc(prompt_tokens)
    if completion_tokens > 0:
        LLM_TOKENS_TOTAL.labels(type="completion", provider=provider, model=model).inc(completion_tokens)


def record_evaluation_run(
    strategy: str,
    status: str,
    metrics: Optional[dict] = None,
) -> None:
    """Record an evaluation run completion and updated Ragas score gauges."""
    EVALUATION_RUNS_TOTAL.labels(strategy=strategy, status=status).inc()
    if metrics:
        for metric_name, score in metrics.items():
            if isinstance(score, (int, float)):
                EVALUATION_METRIC_SCORES.labels(metric=metric_name, strategy=strategy).set(score)


def generate_metrics_output() -> bytes:
    """Generate latest Prometheus exposition format text."""
    return generate_latest(registry)
