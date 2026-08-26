"""Webhook / Payment-State Exception Recovery Service for RecoverX.

This service identifies business-impacting discrepancies between RecoverX local
transaction states and authoritative Razorpay provider state (e.g. DLQ failed
webhook events, dropped network deliveries, or un-synchronized payment transitions).
It creates idempotent `webhook_payment_state_exception` RecoveryCase instances and
executes deterministic resynchronization workflows.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.core.dependencies import verify_merchant_ownership
from app.models.audit_log import AuditLog
from app.models.recovery_case import RecoveryCase
from app.models.transaction import Transaction
from app.models.webhook_event import WebhookEvent
from app.services.razorpay_service import RazorpayService

logger = logging.getLogger(__name__)

STATUS_PRECEDENCE = {
    "created": 1,
    "authorized": 2,
    "payment_verified": 3,
    "captured": 4,
    "action_required": 5,
    "settlement_ready": 6,
    "recovered": 7,
    "failed": 0,
    "refunded": 8,
}


def _audit(
    db: Session,
    merchant_id: int,
    entity_type: str,
    entity_id: str,
    event_type: str,
    details: str,
) -> None:
    db.add(
        AuditLog(
            merchant_id=merchant_id,
            entity_type=entity_type,
            entity_id=entity_id,
            event_type=event_type,
            details=details,
        )
    )


class WebhookRecoveryService:
    def __init__(self, rzp_service: RazorpayService | None = None) -> None:
        self.rzp_service = rzp_service or RazorpayService()

    def detect_payment_mismatch(
        self,
        transaction_id: int,
        merchant_id: int,
        db: Session,
    ) -> RecoveryCase | None:
        """Verify authoritative Razorpay payment state against local RecoverX state.

        Creates or updates a single idempotent RecoveryCase only if an actual business
        mismatch exists (e.g. provider confirms payment captured while local is failed/unresolved).
        """
        transaction = db.scalar(select(Transaction).where(Transaction.id == transaction_id))
        if transaction is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Transaction {transaction_id} not found.",
            )
        verify_merchant_ownership(transaction, merchant_id, "Transaction")

        if not transaction.external_id and not transaction.order_id:
            logger.info("Transaction %s has no external provider identifiers to check", transaction_id)
            return None

        # Query Authoritative Provider State
        provider_data: dict[str, Any] | None = None
        provider_status: str | None = None

        _audit(
            db,
            merchant_id=merchant_id,
            entity_type="transaction",
            entity_id=str(transaction.id),
            event_type="provider_state_checked",
            details=f"Querying authoritative provider state for external_id={transaction.external_id}, order_id={transaction.order_id}",
        )

        try:
            if transaction.external_id and transaction.external_id.startswith("pay_"):
                provider_data = self.rzp_service.fetch_payment(transaction.external_id)
                provider_status = provider_data.get("status")
            elif transaction.order_id and transaction.order_id.startswith("order_"):
                provider_data = self.rzp_service.fetch_order(transaction.order_id)
                order_status = provider_data.get("status")
                # Order status "paid" corresponds to captured payment
                if order_status == "paid":
                    provider_status = "captured"
                elif order_status in {"attempted", "created"}:
                    provider_status = order_status
        except HTTPException as exc:
            if exc.status_code == 404:
                logger.info("Provider entity not found on Razorpay for transaction %s", transaction.id)
                return None
            raise
        except Exception as exc:
            logger.error("Failed to query provider state for transaction %s: %s", transaction.id, exc)
            return None

        if not provider_status:
            return None

        local_status = (transaction.status or "created").lower().strip()
        provider_status = provider_status.lower().strip()

        # Check for business-impacting state mismatch
        # Example: Provider confirms "captured" or "authorized", but local state is "failed", "action_required", "created", or "unknown"
        is_mismatch = False
        if provider_status in {"captured", "authorized", "paid"} and local_status not in {"captured", "authorized", "settlement_ready", "recovered"}:
            is_mismatch = True
        elif provider_status == "failed" and local_status in {"captured", "authorized"}:
            is_mismatch = True

        if not is_mismatch:
            # States agree or benign transition; no recovery case needed
            return None

        _audit(
            db,
            merchant_id=merchant_id,
            entity_type="transaction",
            entity_id=str(transaction.id),
            event_type="state_mismatch_detected",
            details=f"State mismatch detected: local='{local_status}' vs authoritative_provider='{provider_status}'",
        )

        # Idempotent Case Creation / Lookup
        existing_case = db.scalar(
            select(RecoveryCase).where(
                RecoveryCase.transaction_id == transaction.id,
                RecoveryCase.merchant_id == merchant_id,
                RecoveryCase.status.in_(["action_required", "merchant_review", "open", "in_progress", "reconciling"]),
            )
        )

        if existing_case is not None:
            existing_case.exception_type = "webhook_payment_state_exception"
            existing_case.stage = "payment_state_mismatch"
            existing_case.amount_at_risk = transaction.amount
            existing_case.next_best_action = "SYNCHRONIZE_PAYMENT_STATE"
            db.commit()
            return existing_case

        # Create new RecoveryCase for webhook payment-state exception
        amount_at_risk = transaction.amount or Decimal("0.00")
        priority = "CRITICAL" if amount_at_risk >= Decimal("1000000.00") else ("HIGH" if amount_at_risk >= Decimal("100000.00") else "MEDIUM")

        new_case = RecoveryCase(
            merchant_id=merchant_id,
            transaction_id=transaction.id,
            customer_id=transaction.customer_id,
            exception_type="webhook_payment_state_exception",
            status="action_required",
            stage="payment_state_mismatch",
            amount_at_risk=amount_at_risk,
            recovery_probability=Decimal("0.950"),
            priority=priority,
            next_best_action="SYNCHRONIZE_PAYMENT_STATE",
        )
        db.add(new_case)
        db.flush()

        _audit(
            db,
            merchant_id=merchant_id,
            entity_type="recovery_case",
            entity_id=str(new_case.id),
            event_type="webhook_state_exception_detected",
            details=f"Created webhook payment-state recovery case #{new_case.id} for ₹{amount_at_risk}",
        )
        db.commit()
        return new_case

    def resync_payment_state(
        self,
        transaction_id: int,
        merchant_id: int,
        db: Session,
    ) -> dict[str, Any]:
        """Deterministically resynchronize local transaction state with authoritative Razorpay API state."""
        transaction = db.scalar(select(Transaction).where(Transaction.id == transaction_id))
        if transaction is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Transaction {transaction_id} not found.",
            )
        verify_merchant_ownership(transaction, merchant_id, "Transaction")

        _audit(
            db,
            merchant_id=merchant_id,
            entity_type="transaction",
            entity_id=str(transaction.id),
            event_type="resync_started",
            details=f"Initiated payment resynchronization for transaction #{transaction.id}",
        )

        provider_data: dict[str, Any] | None = None
        provider_status: str | None = None

        try:
            if transaction.external_id and transaction.external_id.startswith("pay_"):
                provider_data = self.rzp_service.fetch_payment(transaction.external_id)
                provider_status = provider_data.get("status")
            elif transaction.order_id and transaction.order_id.startswith("order_"):
                provider_data = self.rzp_service.fetch_order(transaction.order_id)
                order_status = provider_data.get("status")
                if order_status == "paid":
                    provider_status = "captured"
                elif order_status in {"attempted", "created"}:
                    provider_status = order_status
        except Exception as exc:
            _audit(
                db,
                merchant_id=merchant_id,
                entity_type="transaction",
                entity_id=str(transaction.id),
                event_type="recovery_failed",
                details=f"Provider API communication failed during resync: {str(exc)[:200]}",
            )
            db.commit()
            return {
                "status": "unresolved",
                "transaction_id": transaction.id,
                "error": "Could not reach Razorpay API to verify payment state.",
                "local_status": transaction.status,
            }

        if not provider_status:
            _audit(
                db,
                merchant_id=merchant_id,
                entity_type="transaction",
                entity_id=str(transaction.id),
                event_type="merchant_review_required",
                details="Authoritative provider status could not be established from Razorpay response.",
            )
            db.commit()
            return {
                "status": "unresolved",
                "transaction_id": transaction.id,
                "reason": "Unknown provider state",
                "local_status": transaction.status,
            }

        prev_status = transaction.status
        transaction.status = provider_status
        transaction.updated_at = datetime.now(UTC)

        # Update associated RecoveryCase
        case = db.scalar(
            select(RecoveryCase).where(
                RecoveryCase.transaction_id == transaction.id,
                RecoveryCase.merchant_id == merchant_id,
            ).order_by(RecoveryCase.id.desc())
        )

        recovery_confirmed = False
        if provider_status in {"captured", "authorized"}:
            recovery_confirmed = True
            if case:
                case.status = "recovered"
                case.stage = "resolved"
                case.amount_at_risk = Decimal("0.00")
                case.next_best_action = "PAYMENT_STATE_SYNCHRONIZED"
                case.updated_at = datetime.now(UTC)

        _audit(
            db,
            merchant_id=merchant_id,
            entity_type="transaction",
            entity_id=str(transaction.id),
            event_type="resync_completed",
            details=f"Synchronized transaction status from '{prev_status}' to '{provider_status}'",
        )

        if recovery_confirmed and case:
            _audit(
                db,
                merchant_id=merchant_id,
                entity_type="recovery_case",
                entity_id=str(case.id),
                event_type="recovery_verified",
                details=f"Payment state verified with provider. Case #{case.id} marked RECOVERED.",
            )

        db.commit()

        return {
            "status": "recovered" if recovery_confirmed else "synchronized",
            "transaction_id": transaction.id,
            "previous_status": prev_status,
            "provider_status": provider_status,
            "local_status": transaction.status,
            "amount": str(transaction.amount),
            "currency": transaction.currency,
            "case_id": case.id if case else None,
            "case_status": case.status if case else None,
        }

    def handle_dlq_event(self, event_id: str, db: Session) -> RecoveryCase | None:
        """Evaluate a dead-lettered webhook event to determine if a business payment exception exists."""
        we = db.scalar(select(WebhookEvent).where(WebhookEvent.event_id == event_id))
        if we is None:
            return None

        payload: dict[str, Any] = {}
        try:
            payload = json.loads(we.payload or "{}")
        except Exception:
            payload = {}

        payment = self.rzp_service.payment_entity(payload)
        payment_id = payment.get("id") if payment else None
        order_id = payload.get("order_id") or (payment.get("order_id") if payment else None)

        tx: Transaction | None = None
        if payment_id:
            tx = db.scalar(select(Transaction).where(Transaction.external_id == payment_id))
        if not tx and order_id:
            tx = db.scalar(select(Transaction).where(Transaction.order_id == order_id))

        if tx:
            return self.detect_payment_mismatch(tx.id, tx.merchant_id or 1, db)

        return None

    def scan_and_detect_unresolved(
        self,
        merchant_id: int,
        db: Session,
        limit: int = 50,
    ) -> list[RecoveryCase]:
        """Targeted scan of unresolved local transactions against Razorpay API."""
        unresolved_txs = list(
            db.scalars(
                select(Transaction)
                .where(
                    Transaction.merchant_id == merchant_id,
                    Transaction.status.in_(["action_required", "failed", "created"]),
                    or_(Transaction.external_id.isnot(None), Transaction.order_id.isnot(None)),
                )
                .order_by(Transaction.id.desc())
                .limit(limit)
            ).all()
        )

        detected_cases: list[RecoveryCase] = []
        for tx in unresolved_txs:
            case = self.detect_payment_mismatch(tx.id, merchant_id, db)
            if case:
                detected_cases.append(case)
        return detected_cases

