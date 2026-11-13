"""Database session management and connectivity verification using SQLAlchemy 2.0."""

import time
from typing import AsyncGenerator, Generator, Optional, Tuple
from sqlalchemy import create_engine, text
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import settings

# Create async engine with connection pooling and health pre-ping
engine = create_async_engine(
    settings.DATABASE_URL,
    echo=False,
    pool_pre_ping=True,
    pool_size=10,
    max_overflow=20,
    future=True,
)

# Async session factory
AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    autocommit=False,
    autoflush=False,
    expire_on_commit=False,
)

# Create sync engine for synchronous Celery workers
sync_engine = create_engine(
    settings.SYNC_DATABASE_URL,
    echo=False,
    pool_pre_ping=True,
    pool_size=5,
    max_overflow=10,
)

SyncSessionLocal = sessionmaker(
    bind=sync_engine,
    autoflush=False,
    autocommit=False,
    expire_on_commit=False,
)


def get_sync_db() -> Generator[Session, None, None]:
    """Provide a synchronous session for worker tasks with clean tenant context isolation."""
    session = SyncSessionLocal()
    try:
        yield session
    except Exception:
        session.rollback()
        raise
    finally:
        try:
            session.execute(text("RESET app.current_tenant_id"))
            session.commit()
        except Exception:
            pass
        session.close()


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Dependency for obtaining an asynchronous database session with clean tenant context isolation."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
        finally:
            try:
                await session.execute(text("RESET app.current_tenant_id"))
                await session.commit()
            except Exception:
                pass
            await session.close()


async def check_db_connectivity(timeout_seconds: float = 3.0) -> Tuple[bool, float, Optional[str]]:
    """Verify connectivity to PostgreSQL by executing a lightweight query.

    Returns:
        Tuple of (is_healthy, latency_ms, error_message)
    """
    start_time = time.perf_counter()
    try:
        async with engine.connect() as conn:
            # Execute simple heartbeat query
            await conn.execute(text("SELECT 1"))
        latency = (time.perf_counter() - start_time) * 1000
        return True, round(latency, 2), None
    except Exception as exc:
        latency = (time.perf_counter() - start_time) * 1000
        return False, round(latency, 2), str(exc)
