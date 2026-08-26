from __future__ import annotations

from contextlib import asynccontextmanager
import logging

from fastapi import FastAPI, Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.api.auth import router as auth_router
from app.api.cases import router as cases_router
from app.api.customers import router as customers_router
from app.api.dashboard import router as dashboard_router
from app.api.disputes import router as disputes_router
from app.api.exceptions import router as exceptions_router
from app.api.payments import router as payments_router
from app.api.settlements import router as settlements_router
from app.api.webhooks import router as webhooks_router
from app.core.config import get_settings
from app.database.connection import ensure_schema
from app.database.session import SessionLocal
from app.middleware.rate_limit import RateLimitMiddleware
from app.middleware.security_headers import SecurityHeadersMiddleware
from app.workers.durable_queue import webhook_queue
from app.workers.tasks import process_razorpay_webhook

settings = get_settings()
logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI):
    ensure_schema()
    webhook_queue.set_handler(process_razorpay_webhook)
    await webhook_queue.start()
    logger.info("RecoverX production engine and durable webhook queue initialized")
    yield
    await webhook_queue.stop()
    logger.info("RecoverX engine gracefully shut down")


app = FastAPI(
    title=settings.app_name,
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/docs" if settings.environment.lower() != "production" else None,
    redoc_url="/redoc" if settings.environment.lower() != "production" else None,
)

# 1. Attach Security Middlewares
app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(RateLimitMiddleware, requests_per_minute=settings.rate_limit_per_minute)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["*"],
    expose_headers=["X-Request-ID"],
)


# 2. Safe Exception Handlers
@app.exception_handler(RequestValidationError)
async def validation_exception_handler(_: Request, exc: RequestValidationError) -> JSONResponse:
    return JSONResponse(
        status_code=422,
        content={"detail": "Invalid request parameters", "errors": jsonable_encoder(exc.errors())},
    )


@app.exception_handler(SQLAlchemyError)
async def database_exception_handler(_: Request, exc: SQLAlchemyError) -> JSONResponse:
    logger.exception("Database request failed: %s", exc)
    return JSONResponse(
        status_code=500,
        content={"detail": "Database operation failed. Request logged for investigation."},
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(_: Request, exc: Exception) -> JSONResponse:
    logger.exception("Unhandled request error: %s", exc)
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error. Request logged for investigation."},
    )


# 3. Observability Health Endpoints
@app.get("/health", tags=["health"])
@app.get("/health/live", tags=["health"])
def health_live() -> dict[str, str]:
    """Process liveness probe."""
    return {"status": "ok", "service": settings.app_name, "environment": settings.environment}


@app.get("/health/ready", tags=["health"])
def health_ready() -> dict[str, str]:
    """Readiness probe checking database connectivity and queue health."""
    try:
        with SessionLocal() as db:
            db.execute(text("SELECT 1"))
        return {
            "status": "ready",
            "database": "connected",
            "durable_queue": "active",
            "service": settings.app_name,
        }
    except Exception as exc:
        logger.error("Health readiness check failed: %s", exc)
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={"status": "unhealthy", "error": "Database connectivity check failed"},
        )


# 4. Include Routers
app.include_router(auth_router)
app.include_router(exceptions_router)
app.include_router(payments_router)
app.include_router(cases_router)
app.include_router(disputes_router)
app.include_router(settlements_router)
app.include_router(customers_router)
app.include_router(dashboard_router)
app.include_router(webhooks_router)
