"""Unified Revenue Exceptions API Endpoints for RecoverX."""

from __future__ import annotations

import logging
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.dependencies import get_current_merchant
from app.database.session import get_db
from app.intelligence.exception_router import ExceptionRouter
from app.models.merchant import Merchant
from app.schemas.revenue_exception import (
    RevenueExceptionDetail,
    RevenueExceptionMetrics,
    RevenueExceptionRead,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/exceptions", tags=["revenue-exceptions"])


@router.get("/metrics", response_model=RevenueExceptionMetrics)
def get_revenue_exception_metrics(
    current_merchant: Merchant = Depends(get_current_merchant),
    db: Session = Depends(get_db),
) -> RevenueExceptionMetrics:
    """Retrieve high-level deterministic financial and operational KPIs across all revenue exceptions."""
    router_engine = ExceptionRouter()
    return router_engine.get_unified_metrics(merchant_id=current_merchant.id, db=db)


@router.get("", response_model=list[RevenueExceptionRead])
def list_revenue_exceptions(
    type: str | None = Query(None, description="Filter by exception_type"),
    status: str | None = Query(None, description="Filter by normalized status"),
    priority: str | None = Query(None, description="Filter by priority (CRITICAL, HIGH, MEDIUM, LOW)"),
    min_amount: Decimal | None = Query(None, description="Filter by minimum amount at risk"),
    deadline_status: str | None = Query(None, description="Filter by deadline urgency"),
    current_merchant: Merchant = Depends(get_current_merchant),
    db: Session = Depends(get_db),
) -> list[RevenueExceptionRead]:
    """Retrieve unified list of revenue exceptions for the authenticated merchant."""
    router_engine = ExceptionRouter()
    return router_engine.get_unified_exceptions(
        merchant_id=current_merchant.id,
        db=db,
        exception_type=type,
        status_filter=status,
        priority_filter=priority,
        min_amount=min_amount,
        deadline_status_filter=deadline_status,
    )


@router.get("/{exception_id}", response_model=RevenueExceptionDetail)
def get_revenue_exception_detail(
    exception_id: int,
    current_merchant: Merchant = Depends(get_current_merchant),
    db: Session = Depends(get_db),
) -> RevenueExceptionDetail:
    """Retrieve single rich unified revenue exception view with timeline audit events."""
    router_engine = ExceptionRouter()
    return router_engine.get_unified_exception_detail(
        case_id=exception_id,
        merchant_id=current_merchant.id,
        db=db,
    )

