"""Settlements & Reconciliation API endpoints for RecoverX."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.dependencies import get_current_merchant, verify_merchant_ownership
from app.database.session import get_db
from app.models.merchant import Merchant
from app.models.reconciliation import ReconciliationRecord
from app.models.settlement import Settlement
from app.schemas.settlement import (
    ReconciliationRecordRead,
    SettlementExceptionRead,
    SettlementMetricsResponse,
    SettlementRead,
    SettlementSyncResponse,
)
from app.services.settlement_sync_service import SettlementSyncService, determine_settlement_failure_action

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/settlements", tags=["settlements"])


@router.get("/metrics", response_model=SettlementMetricsResponse)
def get_settlement_metrics(
    current_merchant: Merchant = Depends(get_current_merchant),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Retrieve aggregate deterministic recovery metrics for settlements."""
    service = SettlementSyncService()
    return service.get_settlement_metrics(current_merchant.id, db)


@router.get("/exceptions", response_model=list[SettlementExceptionRead])
def list_settlement_exceptions(
    current_merchant: Merchant = Depends(get_current_merchant),
    db: Session = Depends(get_db),
) -> list[SettlementExceptionRead]:
    """List active failed and on-hold settlement exceptions requiring merchant attention."""
    query = (
        select(Settlement)
        .where(
            Settlement.merchant_id == current_merchant.id,
            Settlement.status.in_(["failed", "on_hold"]),
        )
        .order_by(Settlement.created_at.desc())
    )
    items = list(db.scalars(query).all())
    return [
        SettlementExceptionRead(
            id=s.id,
            razorpay_settlement_id=s.razorpay_settlement_id,
            amount=s.amount,
            currency=s.currency,
            status=s.status,
            failure_reason=s.failure_reason,
            recommended_action=determine_settlement_failure_action(s.failure_reason),
            created_at=s.created_at,
        )
        for s in items
    ]


@router.get("/reconciliation", response_model=list[ReconciliationRecordRead])
@router.get("/recon/records", response_model=list[ReconciliationRecordRead])
def list_reconciliation_records(
    status: str | None = None,
    current_merchant: Merchant = Depends(get_current_merchant),
    db: Session = Depends(get_db),
) -> list[ReconciliationRecord]:
    """List reconciliation discrepancy records for the authenticated merchant."""
    query = select(ReconciliationRecord).where(ReconciliationRecord.merchant_id == current_merchant.id)
    if status:
        query = query.where(ReconciliationRecord.status == status.lower().strip())
    query = query.order_by(ReconciliationRecord.created_at.desc())
    return list(db.scalars(query).all())


@router.get("", response_model=list[SettlementRead])
def list_settlements(
    status: str | None = None,
    current_merchant: Merchant = Depends(get_current_merchant),
    db: Session = Depends(get_db),
) -> list[Settlement]:
    """List all settlements for the authenticated merchant."""
    query = select(Settlement).where(Settlement.merchant_id == current_merchant.id)
    if status:
        query = query.where(Settlement.status == status.lower().strip())
    query = query.order_by(Settlement.created_at.desc())
    return list(db.scalars(query).all())


@router.get("/{settlement_id}", response_model=SettlementRead)
def get_settlement(
    settlement_id: int,
    current_merchant: Merchant = Depends(get_current_merchant),
    db: Session = Depends(get_db),
) -> Settlement:
    """Get single settlement details ensuring merchant tenancy."""
    settlement = db.scalar(select(Settlement).where(Settlement.id == settlement_id))
    if settlement is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Settlement not found.")
    verify_merchant_ownership(settlement, current_merchant.id, "settlement")
    return settlement


@router.post("/{settlement_id}/sync", response_model=SettlementRead)
def sync_single_settlement(
    settlement_id: int,
    current_merchant: Merchant = Depends(get_current_merchant),
    db: Session = Depends(get_db),
) -> Settlement:
    """Trigger manual re-synchronization of a single settlement from Razorpay API."""
    service = SettlementSyncService()
    return service.sync_settlement_by_id(settlement_id, current_merchant.id, db)


@router.post("/sync-all", response_model=SettlementSyncResponse)
def sync_all_settlements(
    lookback_hours: int | None = Query(None, ge=1, le=720),
    current_merchant: Merchant = Depends(get_current_merchant),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Trigger synchronization of recent settlements from Razorpay API."""
    service = SettlementSyncService()
    return service.sync_settlements(current_merchant.id, db, lookback_hours=lookback_hours)
