"""Application configuration using Pydantic Settings."""

import json
from typing import Any, List, Optional, Union
from pydantic import (
    Field,
    field_validator,
    model_validator,
)
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Core application settings validated against environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )

    # Application Information
    PROJECT_NAME: str = "Enterprise Document Intelligence Platform"
    VERSION: str = "0.2.0"
    API_V1_STR: str = "/api/v1"
    ENVIRONMENT: str = Field(default="development", description="Environment: development, staging, production")
    DEBUG: bool = Field(default=True, description="Debug mode")
    LOG_LEVEL: str = Field(default="INFO", description="Logging level")

    # Security & Tokens
    SECRET_KEY: str = Field(
        default="dev-insecure-secret-key-replace-in-production-min-32-chars",
        description="Application secret key used for signing cryptographic tokens",
    )
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 15
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7

    # Cookie Configuration
    REFRESH_COOKIE_NAME: str = "refresh_token"
    COOKIE_SECURE: bool = False
    COOKIE_SAMESITE: str = "lax"
    COOKIE_DOMAIN: Optional[str] = None

    # CORS
    BACKEND_CORS_ORIGINS: List[str] = [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ]

    @field_validator("BACKEND_CORS_ORIGINS", mode="before")
    @classmethod
    def assemble_cors_origins(cls, v: Union[str, List[str]]) -> List[str]:
        if isinstance(v, str):
            v = v.strip()
            if not v:
                return []
            if v.startswith("[") and v.endswith("]"):
                try:
                    parsed = json.loads(v)
                    if isinstance(parsed, list):
                        return [str(item).strip() for item in parsed if item]
                except json.JSONDecodeError:
                    pass
            return [i.strip() for i in v.split(",") if i.strip()]
        elif isinstance(v, list):
            return [str(i).strip() for i in v if i]
        return []

    # Database (PostgreSQL) - Dedicated Non-Superuser Application Role with NOBYPASSRLS
    POSTGRES_SERVER: str = "localhost"
    POSTGRES_PORT: int = 5432
    POSTGRES_USER: str = "docintel_app"
    POSTGRES_PASSWORD: str = "docintel_secure_pass_2026"
    POSTGRES_DB: str = "doc_intelligence"
    DATABASE_URL_OVERRIDE: Optional[str] = None
    SYNC_DATABASE_URL_OVERRIDE: Optional[str] = None

    @property
    def DATABASE_URL(self) -> str:
        """Async database URL for SQLAlchemy 2.0 with asyncpg."""
        if self.DATABASE_URL_OVERRIDE:
            return self.DATABASE_URL_OVERRIDE
        return (
            f"postgresql+asyncpg://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}"
            f"@{self.POSTGRES_SERVER}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
        )

    @property
    def SYNC_DATABASE_URL(self) -> str:
        """Synchronous database URL for Alembic migrations."""
        if self.SYNC_DATABASE_URL_OVERRIDE:
            return self.SYNC_DATABASE_URL_OVERRIDE
        return (
            f"postgresql+psycopg2://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}"
            f"@{self.POSTGRES_SERVER}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
        )

    # Redis
    REDIS_HOST: str = "localhost"
    REDIS_PORT: int = 6379
    REDIS_DB: int = 0
    REDIS_PASSWORD: Optional[str] = None
    REDIS_URL_OVERRIDE: Optional[str] = None
    RATE_LIMIT_FALLBACK_POLICY: str = Field(
        default="memory",
        description="Fallback policy when Redis is unavailable: 'memory' (process-local sliding window), 'allow' (fail-open), or 'reject' (fail-closed HTTP 429)",
    )

    @property
    def REDIS_URL(self) -> str:
        """Redis connection URL."""
        if self.REDIS_URL_OVERRIDE:
            return self.REDIS_URL_OVERRIDE
        auth = f":{self.REDIS_PASSWORD}@" if self.REDIS_PASSWORD else ""
        return f"redis://{auth}{self.REDIS_HOST}:{self.REDIS_PORT}/{self.REDIS_DB}"

    # Celery
    CELERY_BROKER_URL: Optional[str] = None
    CELERY_RESULT_BACKEND: Optional[str] = None

    @model_validator(mode="after")
    def set_celery_defaults(self) -> "Settings":
        if not self.CELERY_BROKER_URL:
            self.CELERY_BROKER_URL = self.REDIS_URL
        if not self.CELERY_RESULT_BACKEND:
            self.CELERY_RESULT_BACKEND = self.REDIS_URL
        return self

    # Qdrant Vector DB
    QDRANT_HOST: str = "localhost"
    QDRANT_PORT: int = 6333
    QDRANT_GRPC_PORT: int = 6334
    QDRANT_API_KEY: Optional[str] = None
    QDRANT_PREFER_GRPC: bool = False
    QDRANT_COLLECTION_CHUNKS: str = "enterprise_document_chunks"

    # Document Storage & Ingestion
    STORAGE_LOCAL_DIR: str = "storage"
    MAX_UPLOAD_SIZE_BYTES: int = 25 * 1024 * 1024  # 25 MB
    ALLOWED_MIME_TYPES: List[str] = ["application/pdf"]

    # Embedding & Chunking Configuration
    EMBEDDING_MODEL_NAME: str = "BAAI/bge-small-en-v1.5"
    EMBEDDING_DIMENSION: int = 384
    CHUNK_SIZE: int = 500
    CHUNK_OVERLAP: int = 100
    EMBEDDING_BATCH_SIZE: int = 32
    BGE_QUERY_INSTRUCTION: str = "Represent this sentence for searching relevant passages: "

    # Retrieval & Hybrid Search Configuration (Phase 4)
    DEFAULT_VECTOR_TOP_K: int = 20
    DEFAULT_BM25_TOP_K: int = 20
    DEFAULT_HYBRID_TOP_K: int = 10
    MAX_SEARCH_TOP_K: int = 100
    MAX_QUERY_LENGTH: int = 1000
    RRF_K_CONSTANT: int = 60
    RRF_VECTOR_WEIGHT: float = 1.0
    RRF_BM25_WEIGHT: float = 1.0
    BM25_INDEX_DIR: str = "storage/indexes"

    # Neural Reranking Configuration (Phase 5)
    RERANKER_MODEL_NAME: str = "BAAI/bge-reranker-base"
    RERANKER_BATCH_SIZE: int = 32
    RERANKER_MAX_LENGTH: int = 512
    DEFAULT_RERANK_CANDIDATES: int = 30
    DEFAULT_RERANK_TOP_K: int = 10
    RERANKER_DEVICE: Optional[str] = None

    # LLM & RAG Generation Configuration (Phase 6)
    LLM_PROVIDER: str = "openai"
    LLM_MODEL: str = "gpt-4o-mini"
    OPENAI_API_KEY: Optional[str] = None
    LLM_TEMPERATURE: float = 0.1
    LLM_MAX_OUTPUT_TOKENS: int = 1500
    LLM_REQUEST_TIMEOUT: float = 30.0
    MAX_CONTEXT_TOKENS: int = 3000
    MAX_HISTORY_TOKENS: int = 1000

    @property
    def QDRANT_URL(self) -> str:
        """Qdrant REST connection URL."""
        return f"http://{self.QDRANT_HOST}:{self.QDRANT_PORT}"

    @model_validator(mode="after")
    def validate_production_constraints(self) -> "Settings":
        """Enforce production security constraints."""
        if self.ENVIRONMENT.lower() == "production":
            if "*" in self.BACKEND_CORS_ORIGINS:
                raise ValueError("Wildcard '*' CORS origins are strictly disallowed in production.")
            if "insecure" in self.SECRET_KEY.lower():
                raise ValueError("Default or insecure SECRET_KEY cannot be used in production.")
            self.COOKIE_SECURE = True
        return self

    def get_sanitized_dict(self) -> dict[str, Any]:
        """Return application settings with all sensitive secrets masked for logging."""
        data = self.model_dump()
        sensitive_keys = {
            "SECRET_KEY",
            "POSTGRES_PASSWORD",
            "REDIS_PASSWORD",
            "QDRANT_API_KEY",
            "OPENAI_API_KEY",
            "DATABASE_URL_OVERRIDE",
            "SYNC_DATABASE_URL_OVERRIDE",
            "REDIS_URL_OVERRIDE",
            "CELERY_BROKER_URL",
            "CELERY_RESULT_BACKEND",
        }
        sanitized = {}
        for key, val in data.items():
            if key in sensitive_keys and val:
                sanitized[key] = "********"
            else:
                sanitized[key] = val
        sanitized["DATABASE_HOST"] = f"{self.POSTGRES_SERVER}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
        sanitized["REDIS_HOST"] = f"{self.REDIS_HOST}:{self.REDIS_PORT}/{self.REDIS_DB}"
        sanitized["QDRANT_HOST"] = f"{self.QDRANT_HOST}:{self.QDRANT_PORT}"
        return sanitized


settings = Settings()
