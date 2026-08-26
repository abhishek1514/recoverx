from __future__ import annotations

import time
import logging
from collections import defaultdict
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from app.core.config import get_settings

logger = logging.getLogger(__name__)


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Sliding-window in-memory rate limiter per IP, protecting endpoints from abuse."""

    def __init__(self, app: Any, requests_per_minute: int | None = None) -> None:
        super().__init__(app)
        self.requests_per_minute = requests_per_minute or get_settings().rate_limit_per_minute
        self.window_seconds = 60
        self.requests: dict[str, list[float]] = defaultdict(list)

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
        now = time.time()
        cutoff = now - self.window_seconds

        # Clean old timestamps
        client_history = [t for t in self.requests[client_ip] if t > cutoff]
        self.requests[client_ip] = client_history

        if len(client_history) >= self.requests_per_minute:
            logger.warning("Rate limit exceeded for client %s on %s", client_ip, path)
            return JSONResponse(
                status_code=429,
                content={"detail": "Too many requests. Please try again later."},
                headers={"Retry-After": "60"},
            )

        self.requests[client_ip].append(now)
        return await call_next(request)

