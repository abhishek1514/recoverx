"""Dedicated parser and normalizer for Razorpay Dispute webhook events."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.intelligence.dispute_evidence_engine import (
    calculate_deadline_metrics,
    calculate_dispute_priority,
    evaluate_evidence_completeness,
)
from app.models.audit_log import AuditLog
from app.models.dispute import Dispute
from app.models.document import Document
from app.models.recovery_case import RecoveryCase
from app.models.transaction import Transaction

logger = logging.getLogger(__name__)

DISPUTE_STATUS_PRECEDENCE = {
    "open": 1,
    "action_required": 2,
    "under_review": 3,
    "won": 4,
    "lost": 4,
    "closed": 4,
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


def extract_dispute_entity(payload: dict[str, Any]) -> dict[str, Any] | None:
    """Extract dispute entity from nested or root webhook payload structure."""
    nested = payload.get("payload")
    if isinstance(nested, dict):
        disp = nested.get("dispute")
        if isinstance(disp, dict) and isinstance(disp.get("entity"), dict):
            return disp["entity"]
        if isinstance(disp, dict):
            return disp
    root_disp = payload.get("dispute")
    if isinstance(root_disp, dict):
        return root_disp.get("entity") if isinstance(root_disp.get("entity"), dict) else root_disp
    return None


def parse_and_normalize_dispute(
    payload: dict[str, Any],
    event_type: str,
    event_id: str,
    db: Session,
    merchant_id: int = 1,
) -> Dispute:
    """Normalize a Razorpay dispute webhook into a Dispute entity and RecoveryCase."""
    dispute_entity = extract_dispute_entity(payload)
    if not dispute_entity:
        raise ValueError("Dispute event payload did not include a valid dispute entity")

    dispute_id = str(dispute_entity.get("id") or "")
    if not dispute_id:
        raise ValueError("Dispute entity missing ID")

    payment_id = str(dispute_entity.get("payment_id") or "") or None
    currency = str(dispute_entity.get("currency") or "INR").upper()
    amount = normalize_amount(dispute_entity.get("amount"), currency)
    reason_code = str(dispute_entity.get("reason_code") or dispute_entity.get("reason") or "general")
    incoming_status = str(dispute_entity.get("status") or "open").lower()
    phase = str(dispute_entity.get("phase") or "chargeback").lower()

    # Find or initialize associated transaction
    transaction: Transaction | None = None
    if payment_id:
        transaction = db.scalar(
            select(Transaction).where(
                Transaction.merchant_id == merchant_id,
                Transaction.external_id == payment_id,
            )
        )

    if transaction is None:
        tx_external_id = payment_id or f"dispute_tx_{dispute_id}"
        transaction = Transaction(
            merchant_id=merchant_id,
            external_id=tx_external_id,
            amount=amount,
            currency=currency,
            status="action_required",
            event_type=event_type,
        )
        db.add(transaction)
        db.flush()

    # Find existing dispute
    dispute = db.scalar(
        select(Dispute).where(
            Dispute.merchant_id == merchant_id,
            Dispute.razorpay_dispute_id == dispute_id,
        )
    )

    respond_by_dt = _parse_timestamp(dispute_entity.get("respond_by"))
    deducted_at_dt = _parse_timestamp(dispute_entity.get("deducted_at"))
    evidence_submitted_at_dt = _parse_timestamp(dispute_entity.get("evidence_submitted_at"))
    created_at_dt = _parse_timestamp(dispute_entity.get("created_at")) or datetime.now(UTC)

    hours_remaining, deadline_status = calculate_deadline_metrics(respond_by_dt)

    if dispute is None:
        dispute = Dispute(
            merchant_id=merchant_id,
            transaction_id=transaction.id,
            razorpay_dispute_id=dispute_id,
            payment_id=payment_id,
            amount=amount,
            currency=currency,
            reason_code=reason_code,
            status=incoming_status,
            phase=phase,
            respond_by=respond_by_dt,
            deducted_at=deducted_at_dt,
            evidence_submitted_at=evidence_submitted_at_dt,
            created_at=created_at_dt,
            deadline_status=deadline_status,
            contest_status="under_review" if incoming_status == "under_review" else ("won" if incoming_status == "won" else ("lost" if incoming_status in {"lost", "closed"} else "draft")),
        )
        db.add(dispute)
        db.flush()
    else:
        # Out-of-order state precedence: Do not regress terminal status
        curr_rank = DISPUTE_STATUS_PRECEDENCE.get(dispute.status, 0)
        in_rank = DISPUTE_STATUS_PRECEDENCE.get(incoming_status, 0)
        if in_rank >= curr_rank:
            dispute.status = incoming_status
            if incoming_status == "under_review":
                dispute.contest_status = "under_review"
            elif incoming_status == "won":
                dispute.contest_status = "won"
            elif incoming_status in {"lost", "closed"}:
                dispute.contest_status = incoming_status
        else:
            logger.info(
                "Preserved higher dispute status '%s' over incoming status '%s' for dispute %s",
                dispute.status,
                incoming_status,
                dispute.razorpay_dispute_id,
            )

        dispute.amount = amount
        dispute.currency = currency
        dispute.reason_code = reason_code
        dispute.phase = phase
        if respond_by_dt:
            dispute.respond_by = respond_by_dt
            dispute.deadline_status = deadline_status
        if deducted_at_dt:
            dispute.deducted_at = deducted_at_dt
        if evidence_submitted_at_dt:
            dispute.evidence_submitted_at = evidence_submitted_at_dt
        if not dispute.transaction_id:
            dispute.transaction_id = transaction.id

    # Check attached documents for completeness
    docs = list(db.scalars(select(Document).where(Document.dispute_id == dispute.id)).all()) if dispute.id else []
    doc_types = [d.document_type for d in docs]
    completeness, _, _ = evaluate_evidence_completeness(reason_code, doc_types)
    dispute.evidence_completeness = completeness

    # Compute deterministic priority
    dispute.priority = calculate_dispute_priority(
        amount=dispute.amount,
        deadline_status=dispute.deadline_status,
        evidence_completeness=completeness,
        status=dispute.status,
        currency=dispute.currency,
    )

    # Create or update corresponding RecoveryCase
    recovery_case: RecoveryCase | None = None
    if dispute.id:
        recovery_case = db.scalar(
            select(RecoveryCase).where(
                RecoveryCase.merchant_id == merchant_id,
                RecoveryCase.dispute_id == dispute.id,
            )
        )

    if recovery_case is None and transaction:
        recovery_case = db.scalar(
            select(RecoveryCase).where(
                RecoveryCase.merchant_id == merchant_id,
                RecoveryCase.transaction_id == transaction.id,
            )
        )

    # Determine next action & case status
    if dispute.status in {"open", "action_required"}:
        case_status = "action_required"
        next_action = "CONTEST_DISPUTE"
    elif dispute.status == "under_review":
        case_status = "merchant_review"
        next_action = "AWAIT_BANK_REVIEW"
    elif dispute.status == "won":
        case_status = "recovered"
        next_action = "DISPUTE_WON"
    else:  # lost / closed
        case_status = "closed"
        next_action = "DISPUTE_LOST"

    if recovery_case is None:
        recovery_case = RecoveryCase(
            merchant_id=merchant_id,
            transaction_id=transaction.id,
            customer_id=transaction.customer_id if transaction else None,
            exception_type="chargeback_dispute",
            dispute_id=dispute.id,
            status=case_status,
            stage="chargeback_dispute",
            amount_at_risk=dispute.amount,
            recovery_probability=Decimal("0.60") if dispute.status not in {"won", "lost"} else (Decimal("1.00") if dispute.status == "won" else Decimal("0.00")),
            priority=dispute.priority,
            next_best_action=next_action,
        )
        db.add(recovery_case)
    else:
        recovery_case.exception_type = "chargeback_dispute"
        recovery_case.dispute_id = dispute.id
        recovery_case.amount_at_risk = dispute.amount
        recovery_case.status = case_status
        recovery_case.stage = "chargeback_dispute"
        recovery_case.priority = dispute.priority
        recovery_case.next_best_action = next_action
        if dispute.status == "won":
            recovery_case.recovery_probability = Decimal("1.00")
        elif dispute.status in {"lost", "closed"}:
            recovery_case.recovery_probability = Decimal("0.00")

    db.add(
        AuditLog(
            merchant_id=merchant_id,
            entity_type="dispute",
            entity_id=dispute.razorpay_dispute_id,
            event_type=f"webhook_{event_type.replace('.', '_')}",
            details=f"Dispute {dispute.razorpay_dispute_id} normalized: {dispute.status} for {dispute.amount} {dispute.currency} (Event: {event_id}).",
        )
    )

    db.commit()
    db.refresh(dispute)
    logger.info(
        "Successfully normalized Razorpay dispute %s (status: %s, amount: %s %s) for merchant %s",
        dispute.razorpay_dispute_id,
        dispute.status,
        dispute.amount,
        dispute.currency,
        merchant_id,
    )
    return dispute
