"""Dedicated parser and normalizer for Razorpay Settlement webhook events."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.audit_log import AuditLog
from app.models.settlement import Settlement

logger = logging.getLogger(__name__)

SETTLEMENT_STATUS_PRECEDENCE = {
    "pending": 1,
    "on_hold": 2,
    "failed": 3,
    "processed": 4,
}


def _parse_timestamp(val: Any) -> datetime | None:
    if val is None:
        return None
    try:
        return datetime.fromtimestamp(int(val), tz=UTC)
    except (TypeError, ValueError, OSError):
        return None


def normalize_amount(amount: Any, currency: str) -> Decimal:
    value = Decimal(str(amount or 0))
    exponent = 0 if currency.upper() in {"JPY", "KRW"} else 2
    return value / (Decimal(10) ** exponent)


def extract_settlement_entity(payload: dict[str, Any]) -> dict[str, Any] | None:
    """Extract settlement entity from nested or root webhook payload structure."""
    nested = payload.get("payload")
    if isinstance(nested, dict):
        setl = nested.get("settlement")
        if isinstance(setl, dict) and isinstance(setl.get("entity"), dict):
            return setl["entity"]
        if isinstance(setl, dict):
            return setl
    root_setl = payload.get("settlement")
    if isinstance(root_setl, dict):
        return root_setl.get("entity") if isinstance(root_setl.get("entity"), dict) else root_setl
    return None


def parse_and_normalize_settlement(
    payload: dict[str, Any],
    event_type: str,
    event_id: str,
    db: Session,
    merchant_id: int = 1,
) -> Settlement:
    """Normalize a Razorpay settlement webhook into a Settlement entity."""
    settlement_entity = extract_settlement_entity(payload)
    if not settlement_entity:
        raise ValueError("Settlement event payload did not include a valid settlement entity")

    settlement_id = str(settlement_entity.get("id") or "")
    if not settlement_id:
        raise ValueError("Settlement entity missing ID")

    currency = str(settlement_entity.get("currency") or "INR").upper()
    amount = normalize_amount(settlement_entity.get("amount"), currency)
    fees = normalize_amount(settlement_entity.get("fees"), currency)
    tax = normalize_amount(settlement_entity.get("tax"), currency)
    utr = str(settlement_entity.get("utr") or "") or None
    incoming_status = str(settlement_entity.get("status") or "processed").lower()
    failure_reason = str(settlement_entity.get("failure_reason") or "") or None

    settlement = db.scalar(
        select(Settlement).where(
            Settlement.merchant_id == merchant_id,
            Settlement.razorpay_settlement_id == settlement_id,
        )
    )

    if settlement is None:
        settlement = Settlement(
            merchant_id=merchant_id,
            razorpay_settlement_id=settlement_id,
            utr=utr,
            amount=amount,
            fees=fees,
            tax=tax,
            currency=currency,
            status=incoming_status,
            settled_at=_parse_timestamp(settlement_entity.get("settled_at")) or datetime.now(UTC),
            failure_reason=failure_reason,
            created_at=_parse_timestamp(settlement_entity.get("created_at")) or datetime.now(UTC),
        )
        db.add(settlement)
        db.flush()
    else:
        # Out-of-order state precedence: Do not regress processed status
        curr_rank = SETTLEMENT_STATUS_PRECEDENCE.get(settlement.status, 0)
        in_rank = SETTLEMENT_STATUS_PRECEDENCE.get(incoming_status, 0)
        if in_rank >= curr_rank:
            settlement.status = incoming_status
        else:
            logger.info(
                "Preserved higher settlement status '%s' over incoming status '%s' for settlement %s",
                settlement.status,
                incoming_status,
                settlement.razorpay_settlement_id,
            )

        settlement.amount = amount
        settlement.fees = fees
        settlement.tax = tax
        settlement.currency = currency
        if utr:
            settlement.utr = utr
        if settlement_entity.get("settled_at"):
            settlement.settled_at = _parse_timestamp(settlement_entity.get("settled_at"))
        if failure_reason:
            settlement.failure_reason = failure_reason

    db.add(
        AuditLog(
            merchant_id=merchant_id,
            entity_type="settlement",
            entity_id=settlement.razorpay_settlement_id,
            event_type=f"webhook_{event_type.replace('.', '_')}",
            details=f"Settlement {settlement.razorpay_settlement_id} normalized: {settlement.status} for {settlement.amount} {settlement.currency} (UTR: {settlement.utr or 'N/A'}, Event: {event_id}).",
        )
    )

    db.commit()
    db.refresh(settlement)
    logger.info(
        "Successfully normalized Razorpay settlement %s (status: %s, amount: %s %s) for merchant %s",
        settlement.razorpay_settlement_id,
        settlement.status,
        settlement.amount,
        settlement.currency,
        merchant_id,
    )
    return settlement

