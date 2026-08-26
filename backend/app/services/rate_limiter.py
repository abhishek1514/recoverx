"""Production Distributed Rate Limiting Service for RecoverX.

Provides Redis-backed distributed rate limiting for multi-replica horizontal scaling,
with atomic sliding-window accounting and transparent fail-safe fallback to memory
when Redis is unavailable or in development mode.
"""

from __future__ import annotations

import logging
import time
from abc import ABC, abstractmethod
from collections import defaultdict
from typing import Any

from app.core.config import Settings, get_settings

logger = logging.getLogger(__name__)


class RateLimiter(ABC):
    """Abstract interface for application rate limiting."""

    @abstractmethod
    def is_rate_limited(
        self,
        key: str,
        limit: int,
        window_seconds: int = 60,
    ) -> tuple[bool, int, int]:
        """Check if request exceeds rate limit.

        Returns: (is_limited, remaining_quota, retry_after_seconds)
        """
        pass

    @abstractmethod
    def check_health(self) -> bool:
        """Check connectivity and operational health of rate limiting backend."""
        pass


class MemoryRateLimiter(RateLimiter):
    """In-memory sliding-window rate limiter for single-replica / development environments."""

    def __init__(self) -> None:
        self.requests: dict[str, list[float]] = defaultdict(list)

    def is_rate_limited(
        self,
        key: str,
        limit: int,
        window_seconds: int = 60,
    ) -> tuple[bool, int, int]:
        now = time.time()
        cutoff = now - window_seconds

        # Evict timestamps outside the active window
        history = [t for t in self.requests[key] if t > cutoff]
        self.requests[key] = history

        if len(history) >= limit:
            oldest = history[0] if history else now
            retry_after = max(1, int(window_seconds - (now - oldest)))
            return True, 0, retry_after

        self.requests[key].append(now)
        remaining = max(0, limit - len(self.requests[key]))
        return False, remaining, 0

    def check_health(self) -> bool:
        return True


class RedisRateLimiter(RateLimiter):
    """Distributed sliding-window rate limiter utilizing atomic Redis sorted-set pipelines."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.redis_url = self.settings.redis_url
        self._redis_client: Any = None
        self._fallback_limiter = MemoryRateLimiter()

    def _get_client(self) -> Any:
        if self._redis_client is None:
            if not self.redis_url:
                raise ValueError("REDIS_URL must be configured when RATE_LIMIT_BACKEND=redis")
            import redis

            self._redis_client = redis.Redis.from_url(
                self.redis_url,
                socket_timeout=2.0,
                socket_connect_timeout=2.0,
                decode_responses=True,
            )
        return self._redis_client

    def is_rate_limited(
        self,
        key: str,
        limit: int,
        window_seconds: int = 60,
    ) -> tuple[bool, int, int]:
        now = time.time()
        cutoff = now - window_seconds
        redis_key = f"rate_limit:{key}"

        try:
            r = self._get_client()
            pipe = r.pipeline(transaction=True)
            # Atomic sliding-window bucket: remove stale entries, add current timestamp, count active window
            pipe.zremrangebyscore(redis_key, 0, cutoff)
            pipe.zadd(redis_key, {str(now): now})
            pipe.zcard(redis_key)
            pipe.expire(redis_key, window_seconds + 5)
            results = pipe.execute()

            current_count = results[2]
            if current_count > limit:
                # Remove over-quota request timestamp so it doesn't inflate subsequent checks
                r.zrem(redis_key, str(now))
                return True, 0, int(window_seconds)

            remaining = max(0, limit - current_count)
            return False, remaining, 0

        except Exception as exc:
            # Safe fail-over to local memory limiter on transient Redis disruption
            logger.warning(
                "Redis rate limiter encountered error (%s). Engaging fail-safe memory limiter fallback.",
                type(exc).__name__,
            )
            return self._fallback_limiter.is_rate_limited(key, limit, window_seconds)

    def check_health(self) -> bool:
        try:
            r = self._get_client()
            return bool(r.ping())
        except Exception as exc:
            logger.error("Redis rate limiter health check failed: %s", exc)
            return False


_global_rate_limiter: RateLimiter | None = None


def get_rate_limiter() -> RateLimiter:
    """Factory function returning singleton RateLimiter according to application settings."""
    global _global_rate_limiter
    if _global_rate_limiter is None:
        settings = get_settings()
        backend = (settings.rate_limit_backend or "memory").lower().strip()
        if backend == "redis":
            _global_rate_limiter = RedisRateLimiter(settings=settings)
        else:
            _global_rate_limiter = MemoryRateLimiter()
    return _global_rate_limiter

