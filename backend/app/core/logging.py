"""Structured logging configuration for the enterprise application."""

import logging
import re
import sys
from typing import Any
from app.core.config import settings

# Sensitive keyword pattern to scrub from logs
SENSITIVE_PATTERNS = [
    re.compile(r"(password['\"]?\s*[:=]\s*['\"]?)([^'\"\s]+)", re.IGNORECASE),
    re.compile(r"(secret['\"]?\s*[:=]\s*['\"]?)([^'\"\s]+)", re.IGNORECASE),
    re.compile(r"(token['\"]?\s*[:=]\s*['\"]?)([^'\"\s]+)", re.IGNORECASE),
    re.compile(r"(authorization['\"]?\s*[:=]\s*['\"]?Bearer\s+)([^'\"\s]+)", re.IGNORECASE),
    re.compile(r"(api[_-]?key['\"]?\s*[:=]\s*['\"]?)([^'\"\s]+)", re.IGNORECASE),
]


class SensitiveDataFilter(logging.Filter):
    """Filter that masks sensitive tokens, passwords, and API keys from log records."""

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = self._sanitize(record.msg)
        if record.args:
            if isinstance(record.args, dict):
                record.args = {k: self._sanitize(str(v)) for k, v in record.args.items()}
            elif isinstance(record.args, tuple):
                record.args = tuple(self._sanitize(str(arg)) for arg in record.args)
        return True

    @staticmethod
    def _sanitize(text: str) -> str:
        for pattern in SENSITIVE_PATTERNS:
            text = pattern.sub(r"\1********", text)
        return text


class StructuredFormatter(logging.Formatter):
    """Standardized formatter for enterprise observability."""

    def format(self, record: logging.LogRecord) -> str:
        timestamp = self.formatTime(record, self.datefmt or "%Y-%m-%d %H:%M:%S")
        level = record.levelname
        name = record.name
        message = record.getMessage()

        # Format: [2026-11-13 17:00:00] [INFO] [app.main]: Application started
        formatted = f"[{timestamp}] [{level:<7}] [{name}]: {message}"

        if record.exc_info:
            formatted += "\n" + self.formatException(record.exc_info)
        return formatted


def setup_logging() -> None:
    """Initialize structured application logging."""
    log_level = getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO)

    # Root handler
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(StructuredFormatter())
    handler.addFilter(SensitiveDataFilter())

    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)

    # Remove existing handlers to prevent duplicate output
    root_logger.handlers = [handler]

    # Configure third-party loggers to avoid noisy debug output
    logging.getLogger("uvicorn.access").setLevel(logging.INFO)
    logging.getLogger("uvicorn.error").setLevel(logging.INFO)
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING if not settings.DEBUG else logging.INFO)
    logging.getLogger("qdrant_client").setLevel(logging.WARNING)
    logging.getLogger("celery").setLevel(logging.INFO)


def get_logger(name: str = "app") -> logging.Logger:
    """Return a named logger configured with application settings."""
    return logging.getLogger(name)


logger = logging.getLogger("app")
