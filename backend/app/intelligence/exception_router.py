"""Unified Revenue Exception Router & Recovery Intelligence Engine for RecoverX."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.dependencies import verify_merchant_ownership
from app.intelligence.dispute_evidence_engine import calculate_deadline_metrics
from app.models.audit_log import AuditLog
from app.models.dispute import Dispute
from app.models.reconciliation import ReconciliationRecord
from app.models.recovery_case import RecoveryCase
from app.models.settlement import Settlement
from app.models.transaction import Transaction
from app.schemas.revenue_exception import (
    RevenueExceptionDetail,
    RevenueExceptionMetrics,
    RevenueExceptionRead,
    RevenueExceptionTimelineEvent,
)

logger = logging.getLogger(__name__)


def map_normalized_lifecycle_status(
    exception_type: str,
    case_status: str,
    dispute: Dispute | None = None,
    settlement: Settlement | None = None,
    recon: ReconciliationRecord | None = None,
) -> tuple[str, str]:
    """Map workflow entity state to standard normalized lifecycle state (detected, action_required, in_progress, waiting_external, resolved, lost, closed)."""
    if exception_type == "chargeback_dispute" and dispute:
        raw_status = dispute.status
        if raw_status == "won":
            return "resolved", raw_status
        if raw_status == "lost":
            return "lost", raw_status
        if raw_status == "closed":
            return "closed", raw_status
        if raw_status == "under_review" or dispute.contest_status == "submitted":
            return "waiting_external", raw_status
        if dispute.contest_status == "ready_for_review":
            return "in_progress", raw_status
        return "action_required", raw_status

    if exception_type in {"settlement_failure", "settlement_hold"} and settlement:
        raw_status = settlement.status
        if raw_status == "processed":
            return "resolved", raw_status
        if raw_status == "failed":
            return "action_required", raw_status
        if raw_status == "on_hold":
            return "action_required", raw_status
        return "detected", raw_status

    if exception_type == "reconciliation_variance" and recon:
        raw_status = recon.status
        if raw_status == "explained":
            return "resolved", raw_status
        return "action_required", raw_status

    if exception_type == "webhook_payment_state_exception":
        if case_status in {"recovered", "resolved"}:
            return "resolved", case_status
        if case_status in {"reconciling", "processing", "syncing"}:
            return "in_progress", case_status
        if case_status == "merchant_review":
            return "action_required", case_status
        return "action_required", case_status

    # Fallback / standard settlement hold
    if case_status in {"recovered", "approved"}:
        return "resolved", case_status
    if case_status in {"rejected", "lost"}:
        return "lost", case_status
    if case_status == "closed":
        return "closed", case_status
    if case_status in {"under_review", "validating"}:
        return "in_progress", case_status
    return "action_required", case_status


def calculate_unified_priority(
    amount_at_risk: Decimal,
    deadline_status: str,
    normalized_status: str,
    exception_type: str,
) -> str:
    """Deterministically calculate priority level (CRITICAL, HIGH, MEDIUM, LOW)."""
    if normalized_status in {"resolved", "lost", "closed"}:
        return "LOW"

    if deadline_status == "deadline_critical":
        return "CRITICAL"

    if amount_at_risk >= Decimal("1000000.00"):  # ₹10,00,000+
        return "CRITICAL"

    if deadline_status == "deadline_approaching" or amount_at_risk >= Decimal("100000.00"):  # ₹1,00,000+
        return "HIGH"

    if amount_at_risk >= Decimal("25000.00") or exception_type in {"chargeback_dispute", "settlement_failure"}:
        return "MEDIUM"

    return "LOW"


def determine_unified_next_action(
    case: RecoveryCase,
    dispute: Dispute | None = None,
    settlement: Settlement | None = None,
    recon: ReconciliationRecord | None = None,
) -> str:
    """Deterministically determine the next-best-action recommendation."""
    exc_type = case.exception_type or "settlement_hold"

    if exc_type == "chargeback_dispute" and dispute:
        if dispute.status == "won":
            return "DISPUTE_WON"
        if dispute.status == "lost":
            return "DISPUTE_LOST"
        if dispute.contest_status == "submitted" or dispute.status == "under_review":
            return "WAITING_BANK_REVIEW"
        if dispute.contest_status == "ready_for_review":
            return "REVIEW_CONTEST"
        if dispute.evidence_completeness == "complete":
            return "REVIEW_CONTEST"
        return "COLLECT_EVIDENCE"

    if exc_type in {"settlement_failure", "settlement_hold"} and settlement:
        if settlement.status == "processed":
            return "SETTLEMENT_RESOLVED"
        reason = (settlement.failure_reason or "").lower()
        if any(k in reason for k in ["bank", "account", "ifsc", "beneficiary", "name_mismatch"]):
            return "VERIFY_BANK_DETAILS"
        if any(k in reason for k in ["kyc", "document", "identity", "compliance"]):
            return "COMPLETE_REQUIRED_INFORMATION"
        return "REVIEW_SETTLEMENT_FAILURE" if exc_type == "settlement_failure" else "REVIEW_REQUIRED_ACTION"

    if exc_type == "reconciliation_variance":
        return "INVESTIGATE_VARIANCE"

    if exc_type == "webhook_payment_state_exception":
        if case.status in {"recovered", "resolved"}:
            return "PAYMENT_STATE_SYNCHRONIZED"
        if case.status == "merchant_review":
            return "MANUAL_MERCHANT_REVIEW"
        return "SYNCHRONIZE_PAYMENT_STATE"

    return case.next_best_action or "REVIEW_EXCEPTION"


class ExceptionRouter:
    def __init__(self, settings: Any = None) -> None:
        self.settings = settings or get_settings()

    def normalize_case(
        self,
        case: RecoveryCase,
        dispute: Dispute | None = None,
        settlement: Settlement | None = None,
        recon: ReconciliationRecord | None = None,
    ) -> RevenueExceptionRead:
        """Synthesize unified RevenueExceptionRead from RecoveryCase and linked domain entity."""
        exc_type = case.exception_type or "settlement_hold"
        source_entity = "transaction"
        source_id = str(case.transaction_id or case.id)
        currency = "INR"
        deadline = None
        deadline_status = "unknown"
        hours_remaining = None
        reason = "Revenue exception detected."

        if exc_type == "chargeback_dispute" and dispute:
            source_entity = "dispute"
            source_id = dispute.razorpay_dispute_id
            currency = dispute.currency
            deadline = dispute.respond_by
            deadline_status = dispute.deadline_status or "unknown"
            hours_remaining, _ = calculate_deadline_metrics(dispute.respond_by)
            reason = f"Disputed by customer: {dispute.reason_code or 'Chargeback'}"

        elif exc_type in {"settlement_failure", "settlement_hold"} and settlement:
            source_entity = "settlement"
            source_id = settlement.razorpay_settlement_id
            currency = settlement.currency
            reason = settlement.failure_reason or f"Settlement {settlement.status.replace('_', ' ')}"

        elif exc_type == "reconciliation_variance" and recon:
            source_entity = "reconciliation"
            source_id = f"recon_{recon.id}"
            reason = f"Unexplained settlement variance of ₹{recon.discrepancy_amount}"

        elif exc_type == "webhook_payment_state_exception":
            source_entity = "transaction"
            source_id = str(case.transaction_id or case.id)
            if case.transaction:
                currency = case.transaction.currency
                source_id = case.transaction.external_id or str(case.transaction.id)
            reason = "Payment state mismatch or webhook processing inconsistency."

        norm_status, provider_status = map_normalized_lifecycle_status(
            exception_type=exc_type,
            case_status=case.status,
            dispute=dispute,
            settlement=settlement,
            recon=recon,
        )

        amount_at_risk = case.amount_at_risk or Decimal("0.00")
        priority = calculate_unified_priority(
            amount_at_risk=amount_at_risk,
            deadline_status=deadline_status,
            normalized_status=norm_status,
            exception_type=exc_type,
        )
        rec_action = determine_unified_next_action(
            case=case,
            dispute=dispute,
            settlement=settlement,
            recon=recon,
        )

        resolved_at = case.updated_at if norm_status in {"resolved", "lost", "closed"} else None

        return RevenueExceptionRead(
            id=case.id,
            merchant_id=case.merchant_id or 1,
            exception_type=exc_type,
            source_entity=source_entity,
            source_id=source_id,
            amount_at_risk=amount_at_risk,
            currency=currency,
            priority=priority,
            status=norm_status,
            provider_status=provider_status,
            deadline=deadline,
            deadline_status=deadline_status,
            hours_remaining=hours_remaining,
            reason=reason,
            recommended_action=rec_action,
            created_at=case.created_at,
            updated_at=case.updated_at,
            resolved_at=resolved_at,
        )

    def get_unified_exceptions(
        self,
        merchant_id: int,
        db: Session,
        exception_type: str | None = None,
        status_filter: str | None = None,
        priority_filter: str | None = None,
        min_amount: Decimal | None = None,
        deadline_status_filter: str | None = None,
    ) -> list[RevenueExceptionRead]:
        """Fetch all merchant recovery cases with joined entities in a single efficient query (no N+1)."""
        query = (
            select(RecoveryCase, Dispute, Settlement, ReconciliationRecord)
            .outerjoin(Dispute, RecoveryCase.dispute_id == Dispute.id)
            .outerjoin(Settlement, RecoveryCase.settlement_id == Settlement.id)
            .outerjoin(ReconciliationRecord, RecoveryCase.reconciliation_record_id == ReconciliationRecord.id)
            .where(RecoveryCase.merchant_id == merchant_id)
            .order_by(RecoveryCase.created_at.desc())
        )

        rows = db.execute(query).all()
        results: list[RevenueExceptionRead] = []

        for case, disp, setl, recon in rows:
            exc = self.normalize_case(case=case, dispute=disp, settlement=setl, recon=recon)

            # Apply in-memory filters
            if exception_type and exc.exception_type != exception_type:
                continue
            if status_filter and exc.status != status_filter:
                continue
            if priority_filter and exc.priority != priority_filter:
                continue
            if min_amount is not None and exc.amount_at_risk < min_amount:
                continue
            if deadline_status_filter and exc.deadline_status != deadline_status_filter:
                continue

            results.append(exc)

        # Sort by priority rank: CRITICAL > HIGH > MEDIUM > LOW
        priority_order = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3}
        results.sort(key=lambda x: (priority_order.get(x.priority, 4), -x.amount_at_risk))
        return results

    def get_unified_metrics(self, merchant_id: int, db: Session) -> RevenueExceptionMetrics:
        """Calculate accurate, non-double-counted financial and operational recovery metrics."""
        exceptions = self.get_unified_exceptions(merchant_id=merchant_id, db=db)

        total_exceptions = len(exceptions)
        total_amount_at_risk = Decimal("0.00")
        critical_count = 0
        high_count = 0
        action_required_count = 0

        dispute_at_risk = Decimal("0.00")
        settlement_at_risk = Decimal("0.00")
        recon_at_risk = Decimal("0.00")

        amount_recovered = Decimal("0.00")
        amount_lost = Decimal("0.00")

        for exc in exceptions:
            if exc.status in {"action_required", "in_progress", "waiting_external", "detected"}:
                total_amount_at_risk += exc.amount_at_risk
                if exc.priority == "CRITICAL":
                    critical_count += 1
                elif exc.priority == "HIGH":
                    high_count += 1
                if exc.status == "action_required":
                    action_required_count += 1

                if exc.exception_type == "chargeback_dispute":
                    dispute_at_risk += exc.amount_at_risk
                elif exc.exception_type in {"settlement_failure", "settlement_hold"}:
                    settlement_at_risk += exc.amount_at_risk
                elif exc.exception_type == "reconciliation_variance":
                    recon_at_risk += exc.amount_at_risk

            elif exc.status == "resolved":
                amount_recovered += exc.amount_at_risk
            elif exc.status == "lost":
                amount_lost += exc.amount_at_risk

        resolved_pool = amount_recovered + amount_lost
        recovery_rate = (amount_recovered / resolved_pool).quantize(Decimal("0.01")) if resolved_pool > Decimal("0.00") else Decimal("1.00")

        return RevenueExceptionMetrics(
            total_exceptions=total_exceptions,
            total_amount_at_risk=total_amount_at_risk,
            critical_count=critical_count,
            high_count=high_count,
            action_required_count=action_required_count,
            dispute_amount_at_risk=dispute_at_risk,
            settlement_amount_at_risk=settlement_at_risk,
            reconciliation_amount_at_risk=recon_at_risk,
            amount_recovered=amount_recovered,
            amount_lost=amount_lost,
            recovery_rate=recovery_rate,
            currency="INR",
        )

    def get_unified_exception_detail(
        self,
        case_id: int,
        merchant_id: int,
        db: Session,
    ) -> RevenueExceptionDetail:
        """Synthesize rich unified single-exception workspace with timeline audit trail."""
        case = db.scalar(select(RecoveryCase).where(RecoveryCase.id == case_id))
        if case is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Revenue exception not found.")
        verify_merchant_ownership(case, merchant_id, "recovery_case")

        dispute = db.scalar(select(Dispute).where(Dispute.id == case.dispute_id)) if case.dispute_id else None
        settlement = db.scalar(select(Settlement).where(Settlement.id == case.settlement_id)) if case.settlement_id else None
        recon = db.scalar(select(ReconciliationRecord).where(ReconciliationRecord.id == case.reconciliation_record_id)) if case.reconciliation_record_id else None
        tx = db.scalar(select(Transaction).where(Transaction.id == case.transaction_id)) if case.transaction_id else None

        base = self.normalize_case(case=case, dispute=dispute, settlement=settlement, recon=recon)

        # Audit Timeline Synthesis
        timeline: list[RevenueExceptionTimelineEvent] = [
            RevenueExceptionTimelineEvent(
                event="exception_detected",
                timestamp=case.created_at,
                description=f"Revenue exception detected ({base.exception_type}) with ₹{base.amount_at_risk} at risk.",
            )
        ]

        if dispute and dispute.contest_submitted_at:
            timeline.append(
                RevenueExceptionTimelineEvent(
                    event="contest_submitted",
                    timestamp=dispute.contest_submitted_at,
                    description=f"Merchant approved dispute contest defense and submitted to Razorpay.",
                    source="merchant",
                )
            )

        if base.status == "resolved" and base.resolved_at:
            timeline.append(
                RevenueExceptionTimelineEvent(
                    event="revenue_recovered",
                    timestamp=base.resolved_at,
                    description=f"Exception resolved and ₹{base.amount_at_risk} revenue protected/recovered.",
                    source="provider",
                )
            )

        return RevenueExceptionDetail(
            **base.model_dump(),
            description=f"Autonomous resolution tracking for {base.exception_type.replace('_', ' ')} on {base.source_id}.",
            customer_id=str(case.customer_id) if case.customer_id else None,
            order_id=tx.order_id if tx else None,
            payment_id=tx.external_id if tx else None,
            utr=settlement.utr if settlement else None,
            evidence_completeness=dispute.evidence_completeness if dispute else None,
            contest_summary=dispute.contest_summary if dispute else None,
            ai_explanation=f"AI Summary: Exception is classified as {base.priority} priority with recommended action '{base.recommended_action}'.",
            timeline=timeline,
        )

