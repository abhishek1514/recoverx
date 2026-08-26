from __future__ import annotations

import logging
from typing import Any
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from app.core.config import get_settings
from app.services.rate_limiter import get_rate_limiter

logger = logging.getLogger(__name__)


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Production distributed rate limiter per IP/tenant, protecting endpoints from abuse."""

    def __init__(self, app: Any, requests_per_minute: int | None = None) -> None:
        super().__init__(app)
        self.requests_per_minute = requests_per_minute or get_settings().rate_limit_per_minute
        self.window_seconds = 60

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        path = request.url.path

        # Whitelist health checks and webhook endpoints from standard user throttling
        if path.startswith("/health") or path.startswith("/api/webhooks/razorpay"):
            return await call_next(request)

        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            client_ip = forwarded.split(",")[0].strip()
        else:
            client_ip = request.client.host if request.client else "unknown"

        limiter = get_rate_limiter()
        is_limited, remaining, retry_after = limiter.is_rate_limited(
            key=client_ip,
            limit=self.requests_per_minute,
            window_seconds=self.window_seconds,
        )

        if is_limited:
            logger.warning("Rate limit exceeded for client %s on %s", client_ip, path)
            return JSONResponse(
                status_code=429,
                content={"detail": "Too many requests. Please try again later."},
                headers={
                    "Retry-After": str(retry_after),
                    "X-RateLimit-Limit": str(self.requests_per_minute),
                    "X-RateLimit-Remaining": "0",
                },
            )

        response = await call_next(request)
        response.headers["X-RateLimit-Limit"] = str(self.requests_per_minute)
        response.headers["X-RateLimit-Remaining"] = str(remaining)
        return response

