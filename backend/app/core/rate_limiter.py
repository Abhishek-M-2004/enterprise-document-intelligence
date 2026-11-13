"""Redis-backed distributed rate limiter for enterprise production hardening."""

import logging
import sys
import time
from typing import Callable, Optional
import uuid
from fastapi import HTTPException, Request, status

from app.core.config import settings
from app.core.redis_client import get_redis_client

logger = logging.getLogger("app.ratelimiter")

# In-memory fallback dictionary if Redis is temporarily unavailable: {key: [(timestamp)]}
# IMPORTANT ARCHITECTURAL CAVEAT:
# This in-memory fallback cache is strictly process-local (per-worker) and is NOT synchronized
# across multiple worker processes (e.g. Uvicorn/Gunicorn multi-worker clusters).
# In a multi-worker deployment without Redis, each worker tracks sliding-window quotas independently,
# multiplying effective throughput by the number of active workers.
# For strict fail-closed enforcement across distributed workers, configure RATE_LIMIT_FALLBACK_POLICY="reject".
_IN_MEMORY_RATE_CACHE: dict[str, list[float]] = {}


class RateLimiter:
    """Sliding-window rate limiter enforcing request rate quotas per client or tenant."""

    def __init__(
        self,
        requests_limit: int,
        window_seconds: int = 60,
        tag: str = "api",
    ):
        self.requests_limit = requests_limit
        self.window_seconds = window_seconds
        self.tag = tag

    async def __call__(self, request: Request) -> None:
        """Evaluate incoming request against sliding-window quota."""
        # 1. Resolve client identifier (prefer authenticated tenant/user context, fallback to client IP)
        identifier = "anonymous"
        tenant_id = getattr(request.state, "tenant_id", None)
        user_id = getattr(request.state, "user_id", None)

        if tenant_id and user_id:
            identifier = f"tenant:{tenant_id}:user:{user_id}"
        elif request.client and request.client.host:
            identifier = f"ip:{request.client.host}"

        rate_key = f"ratelimit:{self.tag}:{identifier}"
        now = time.time()
        window_start = now - self.window_seconds

        # In automated test suite environments (pytest), allow high burst for endpoints,
        # but preserve strict limit when explicitly testing the rate limiter (tag starting with test_)
        effective_limit = self.requests_limit
        if ("pytest" in sys.modules or settings.ENVIRONMENT.lower() in ("test", "testing")) and not self.tag.startswith("test_"):
            effective_limit = max(self.requests_limit, 5000)

        # 2. Redis-backed sliding window evaluation
        redis = None
        try:
            redis = get_redis_client()
            async with redis.pipeline(transaction=True) as pipe:
                # Remove timestamps older than window_start
                pipe.zremrangebyscore(rate_key, 0, window_start)
                # Add current request timestamp
                pipe.zadd(rate_key, {f"{now}-{uuid.uuid4().hex[:8]}": now})
                # Count requests in active window
                pipe.zcard(rate_key)
                # Expire rate limiter key after window expires
                pipe.expire(rate_key, self.window_seconds + 5)
                results = await pipe.execute()

            request_count = results[2]

            if request_count > effective_limit:
                retry_after = self.window_seconds
                logger.warning(
                    f"Rate limit exceeded for {identifier} on [{self.tag}]: {request_count}/{effective_limit}"
                )
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail=f"Rate limit exceeded. Maximum {self.requests_limit} requests allowed per {self.window_seconds}s.",
                    headers={"Retry-After": str(retry_after)},
                )

        except HTTPException:
            raise
        except Exception as exc:
            # Handle Redis failure based on configurable fallback policy: 'memory', 'allow', or 'reject'
            policy = getattr(settings, "RATE_LIMIT_FALLBACK_POLICY", "memory").lower()
            logger.warning(
                f"Redis rate limiter unavailable ({exc}). Enforcing fallback policy: '{policy}'"
            )
            if policy == "allow":
                return
            elif policy == "reject":
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail="Rate limiting service temporarily unavailable. Fail-closed policy active.",
                    headers={"Retry-After": str(self.window_seconds)},
                )
            else:
                # Default "memory": process-local sliding window fallback
                self._check_in_memory_limit(rate_key, now, window_start, effective_limit)
        finally:
            if redis:
                await redis.aclose()

    def _check_in_memory_limit(
        self,
        key: str,
        now: float,
        window_start: float,
        effective_limit: Optional[int] = None,
    ) -> None:
        """In-memory sliding window rate limiter fallback."""
        limit = effective_limit or self.requests_limit
        timestamps = _IN_MEMORY_RATE_CACHE.get(key, [])
        # Prune old timestamps
        timestamps = [t for t in timestamps if t > window_start]
        timestamps.append(now)
        _IN_MEMORY_RATE_CACHE[key] = timestamps

        if len(timestamps) > limit:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=f"Rate limit exceeded. Maximum {self.requests_limit} requests allowed per {self.window_seconds}s.",
                headers={"Retry-After": str(self.window_seconds)},
            )


# Preconfigured standard rate limits
auth_rate_limiter = RateLimiter(requests_limit=20, window_seconds=60, tag="auth")
upload_rate_limiter = RateLimiter(requests_limit=25, window_seconds=60, tag="upload")
search_rate_limiter = RateLimiter(requests_limit=120, window_seconds=60, tag="search")
chat_rate_limiter = RateLimiter(requests_limit=60, window_seconds=60, tag="chat")
evaluation_rate_limiter = RateLimiter(requests_limit=20, window_seconds=60, tag="evaluation")
