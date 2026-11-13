"""Distributed tracing using OpenTelemetry across RAG ingestion and retrieval workflows."""

from contextlib import contextmanager
import functools
import logging
import time
from typing import Any, Callable, Dict, Iterator, Optional

from opentelemetry import trace
from opentelemetry.trace import Status, StatusCode

logger = logging.getLogger("app.tracing")

# Initialize global tracer for the platform
tracer = trace.get_tracer("enterprise-rag-platform", "1.0.0")


@contextmanager
def trace_span(
    name: str,
    attributes: Optional[Dict[str, Any]] = None,
) -> Iterator[trace.Span]:
    """Context manager for tracing an operational stage in the RAG pipeline.

    Captures execution status and duration, recording sanitized telemetry.
    Confidential document text, passwords, and API keys are never stored as span attributes.
    """
    span = tracer.start_span(name)
    start_time = time.perf_counter()

    if attributes:
        for key, value in attributes.items():
            if value is not None and not any(s in key.lower() for s in ["key", "secret", "password", "token", "content", "document_text"]):
                span.set_attribute(key, str(value) if not isinstance(value, (int, float, bool)) else value)

    try:
        yield span
        span.set_status(Status(StatusCode.OK))
    except Exception as exc:
        span.set_status(Status(StatusCode.ERROR, description=str(exc)))
        span.record_exception(exc)
        raise
    finally:
        duration_ms = (time.perf_counter() - start_time) * 1000
        span.set_attribute("duration_ms", round(duration_ms, 2))
        span.end()


def traced(span_name: Optional[str] = None) -> Callable:
    """Decorator to trace asynchronous or synchronous service methods."""
    def decorator(func: Callable) -> Callable:
        name = span_name or f"{func.__module__}.{func.__qualname__}"

        if functools.iscoroutinefunction(func):
            @functools.wraps(func)
            async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
                with trace_span(name):
                    return await func(*args, **kwargs)
            return async_wrapper
        else:
            @functools.wraps(func)
            def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
                with trace_span(name):
                    return func(*args, **kwargs)
            return sync_wrapper

    return decorator
