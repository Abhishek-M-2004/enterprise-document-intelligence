"""Redis client configuration and connectivity verification."""

import time
from typing import Optional, Tuple
import redis.asyncio as aioredis
from app.core.config import settings


def get_redis_client() -> aioredis.Redis:
    """Create an asynchronous Redis client instance."""
    return aioredis.from_url(
        settings.REDIS_URL,
        socket_timeout=3.0,
        socket_connect_timeout=3.0,
        decode_responses=True,
    )


async def check_redis_connectivity() -> Tuple[bool, float, Optional[str]]:
    """Verify connectivity to Redis via PING command.

    Returns:
        Tuple of (is_healthy, latency_ms, error_message)
    """
    start_time = time.perf_counter()
    client = None
    try:
        client = get_redis_client()
        pong = await client.ping()
        latency = (time.perf_counter() - start_time) * 1000
        if pong:
            return True, round(latency, 2), None
        return False, round(latency, 2), "Ping response was false"
    except Exception as exc:
        latency = (time.perf_counter() - start_time) * 1000
        return False, round(latency, 2), str(exc)
    finally:
        if client:
            await client.aclose()
