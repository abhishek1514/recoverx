"""Dedicated Settlement and Reconciliation Synchronization Service for RecoverX."""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.dependencies import verify_merchant_ownership
from app.models.audit_log import AuditLog
from app.models.merchant import Merchant
from app.models.reconciliation import ReconciliationRecord
from app.models.recovery_case import RecoveryCase
from app.models.settlement import Settlement
from app.models.transaction import Transaction
from app.services.razorpay_service import RazorpayService
from app.services.settlement_parser import SETTLEMENT_STATUS_PRECEDENCE, normalize_amount

logger = logging.getLogger(__name__)

VERIFIED_SETTLEMENT_STATUSES = {"created", "processed", "failed", "on_hold"}


def _parse_timestamp(val: Any) -> datetime | None:
    if val is None:
        return None
    try:
        return datetime.fromtimestamp(int(val), tz=UTC)
    except (TypeError, ValueError, OSError):
        return None


def determine_settlement_failure_action(failure_reason: str | None) -> str:
    """Deterministically map settlement failure reason to recommended next action."""
    if not failure_reason:
        return "CONTACT_RAZORPAY_SUPPORT"
    clean = failure_reason.lower()
    if any(k in clean for k in ["invalid_account", "account_number", "account_closed", "beneficiary", "ifsc", "name_mismatch", "bank_account", "account error", "invalid ifsc"]):
        return "VERIFY_BANK_ACCOUNT"
    if any(k in clean for k in ["kyc", "document", "identity", "pan", "gstin", "compliance", "verification"]):
        return "COMPLETE_REQUIRED_INFORMATION"
    return "CONTACT_RAZORPAY_SUPPORT"


class SettlementSyncService:
    def __init__(self, rzp_service: RazorpayService | None = None) -> None:
        self.rzp_service = rzp_service or RazorpayService()
        self.settings = get_settings()

    def sync_settlements(
        self,
        merchant_id: int,
        db: Session,
        lookback_hours: int | None = None,
        batch_size: int | None = None,
    ) -> dict[str, Any]:
        """Fetch and idempotently synchronize settlements from Razorpay with pagination and state-precedence."""
        hours = lookback_hours if lookback_hours is not None else self.settings.settlement_sync_lookback_hours
        count = batch_size if batch_size is not None else self.settings.settlement_sync_batch_size
        now = datetime.now(UTC)
        from_ts = int((now - timedelta(hours=hours)).timestamp())

        skip = 0
        total_synced = 0
        exceptions_detected = 0

        while True:
            try:
                items = self.rzp_service.get_settlements(
                    from_timestamp=from_ts,
                    to_timestamp=int(now.timestamp()),
                    count=count,
                    skip=skip,
                )
            except Exception as exc:
                logger.error("Failed fetching settlements from Razorpay at skip=%s: %s", skip, exc)
                break

            if not items:
                break

            for item in items:
                settlement, is_exception = self._upsert_settlement_item(item, merchant_id, db)
                total_synced += 1
                if is_exception:
                    exceptions_detected += 1

            if len(items) < count:
                break
            skip += count

        db.commit()
        logger.info(
            "Settlement sync completed for merchant %s: %s records processed, %s exceptions detected.",
            merchant_id,
            total_synced,
            exceptions_detected,
        )
        return {
            "status": "success",
            "total_synced": total_synced,
            "exceptions_detected": exceptions_detected,
            "timestamp": now.isoformat(),
        }

    def sync_settlement_by_id(
        self,
        settlement_id: int,
        merchant_id: int,
        db: Session,
    ) -> Settlement:
        """Synchronize a single settlement record from Razorpay API."""
        settlement = db.scalar(select(Settlement).where(Settlement.id == settlement_id))
        if settlement is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Settlement record not found.")
        verify_merchant_ownership(settlement, merchant_id, "settlement")

        try:
            raw_item = self.rzp_service.get_settlement_by_id(settlement.razorpay_settlement_id)
            updated_settlement, _ = self._upsert_settlement_item(raw_item, merchant_id, db)
            db.commit()
            db.refresh(updated_settlement)
            return updated_settlement
        except HTTPException:
            raise
        except Exception as exc:
            logger.error("Error synchronizing settlement %s: %s", settlement.razorpay_settlement_id, exc)
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Could not synchronize settlement status from Razorpay.",
            ) from exc

    def _upsert_settlement_item(
        self,
        item: dict[str, Any],
        merchant_id: int,
        db: Session,
    ) -> tuple[Settlement, bool]:
        """Normalize, state-rank, and upsert single settlement object with exception tracking."""
        rzp_id = str(item.get("id") or "").strip()
        if not rzp_id:
            raise ValueError("Settlement item missing ID")

        currency = str(item.get("currency") or "INR").upper()
        amount = normalize_amount(item.get("amount"), currency)
        fees = normalize_amount(item.get("fees"), currency)
        tax = normalize_amount(item.get("tax"), currency)
        utr = str(item.get("utr") or "").strip() or None

        raw_status = str(item.get("status") or "created").lower().strip()
        normalized_status = raw_status if raw_status in VERIFIED_SETTLEMENT_STATUSES else "unknown"

        failure_reason = item.get("failure_reason") or item.get("error_description") or None
        if failure_reason:
            failure_reason = str(failure_reason).strip()

        settled_at = _parse_timestamp(item.get("settled_at"))
        created_at = _parse_timestamp(item.get("created_at")) or datetime.now(UTC)

        settlement = db.scalar(
            select(Settlement).where(
                Settlement.merchant_id == merchant_id,
                Settlement.razorpay_settlement_id == rzp_id,
            )
        )

        is_exception = False

        if settlement is None:
            settlement = Settlement(
                merchant_id=merchant_id,
                razorpay_settlement_id=rzp_id,
                utr=utr,
                amount=amount,
                fees=fees,
                tax=tax,
                currency=currency,
                status=normalized_status,
                settled_at=settled_at,
                failure_reason=failure_reason,
                created_at=created_at,
            )
            db.add(settlement)
            db.flush()
        else:
            # Enforce out-of-order state precedence
            curr_rank = SETTLEMENT_STATUS_PRECEDENCE.get(settlement.status, 0)
            in_rank = SETTLEMENT_STATUS_PRECEDENCE.get(normalized_status, 0)
            if in_rank >= curr_rank:
                settlement.status = normalized_status
            else:
                logger.info(
                    "Preserved higher settlement status '%s' over incoming status '%s' for %s",
                    settlement.status,
                    normalized_status,
                    settlement.razorpay_settlement_id,
                )

            settlement.amount = amount
            settlement.fees = fees
            settlement.tax = tax
            settlement.currency = currency
            if utr:
                settlement.utr = utr
            if settled_at:
                settlement.settled_at = settled_at
            if failure_reason:
                settlement.failure_reason = failure_reason

        # Exception Evaluation & RecoveryCase Linking
        if settlement.status in {"failed", "on_hold"}:
            is_exception = True
            exc_type = "settlement_failure" if settlement.status == "failed" else "settlement_hold"
            next_action = determine_settlement_failure_action(settlement.failure_reason)

            # Ensure associated transaction record exists for strict DB foreign key consistency
            tx = db.scalar(
                select(Transaction).where(
                    Transaction.merchant_id == merchant_id,
                    Transaction.external_id == f"setl_tx_{settlement.id}",
                )
            )
            if tx is None:
                tx = Transaction(
                    merchant_id=merchant_id,
                    external_id=f"setl_tx_{settlement.id}",
                    amount=settlement.amount,
                    currency=settlement.currency,
                    status="action_required",
                    event_type="settlement.exception",
                )
                db.add(tx)
                db.flush()

            # Idempotent case creation
            case = db.scalar(
                select(RecoveryCase).where(
                    RecoveryCase.merchant_id == merchant_id,
                    RecoveryCase.settlement_id == settlement.id,
                )
            )
            if case is None:
                case = RecoveryCase(
                    merchant_id=merchant_id,
                    transaction_id=tx.id,
                    settlement_id=settlement.id,
                    exception_type=exc_type,
                    status="action_required",
                    stage="settlement_exception",
                    amount_at_risk=settlement.amount,
                    recovery_probability=Decimal("0.85"),
                    priority="HIGH",
                    next_best_action=next_action,
                )
                db.add(case)
            else:
                case.exception_type = exc_type
                case.amount_at_risk = settlement.amount
                if settlement.status == "failed":
                    case.status = "action_required"
                    case.next_best_action = next_action

            db.add(
                AuditLog(
                    merchant_id=merchant_id,
                    entity_type="settlement",
                    entity_id=settlement.razorpay_settlement_id,
                    event_type=f"settlement_exception_{settlement.status}",
                    details=f"Settlement exception detected: {settlement.status} (Amount: {settlement.amount} {settlement.currency}, Reason: {settlement.failure_reason or 'unknown'}).",
                )
            )

        elif settlement.status == "processed":
            # If linked recovery case exists, mark resolved
            case = db.scalar(
                select(RecoveryCase).where(
                    RecoveryCase.merchant_id == merchant_id,
                    RecoveryCase.settlement_id == settlement.id,
                )
            )
            if case and case.status != "recovered":
                case.status = "recovered"
                case.recovery_probability = Decimal("1.00")
                case.next_best_action = "SETTLEMENT_RESOLVED"
                db.add(
                    AuditLog(
                        merchant_id=merchant_id,
                        entity_type="recovery_case",
                        entity_id=str(case.id),
                        event_type="settlement_recovered",
                        details=f"Settlement {settlement.razorpay_settlement_id} confirmed processed by Razorpay. Case resolved.",
                    )
                )

        return settlement, is_exception

    def sync_reconciliation_records(
        self,
        year: int,
        month: int,
        day: int,
        merchant_id: int,
        db: Session,
    ) -> list[ReconciliationRecord]:
        """Fetch transaction-level recon and deterministically categorize explained vs unexplained discrepancies."""
        recon_data = self.rzp_service.get_combined_recon_settlements(year, month, day)
        items = recon_data.get("items", []) if isinstance(recon_data, dict) else []

        records: list[ReconciliationRecord] = []
        for item in items:
            expected = Decimal(str(item.get("amount", 0))) / Decimal("100")
            settled = Decimal(str(item.get("settled_amount", 0))) / Decimal("100")
            fee = Decimal(str(item.get("fee", 0))) / Decimal("100")
            tax = Decimal(str(item.get("tax", 0))) / Decimal("100")
            refund = Decimal(str(item.get("refund", 0))) / Decimal("100")
            adjustment = Decimal(str(item.get("adjustment", 0))) / Decimal("100")

            # Deterministic balance formula
            explained_sum = settled + fee + tax + refund + adjustment
            unexplained_discrepancy = abs(expected - explained_sum)

            status_val = "explained" if unexplained_discrepancy <= self.settings.reconciliation_variance_threshold else "unexplained"

            recon = ReconciliationRecord(
                merchant_id=merchant_id,
                expected_amount=expected,
                settled_amount=settled,
                fee_amount=fee,
                tax_amount=tax,
                refund_amount=refund,
                adjustment_amount=adjustment,
                discrepancy_amount=unexplained_discrepancy,
                discrepancy_type=item.get("type", "standard_settlement"),
                status=status_val,
            )
            db.add(recon)
            db.flush()
            records.append(recon)

            if status_val == "unexplained":
                tx = Transaction(
                    merchant_id=merchant_id,
                    external_id=f"recon_tx_{recon.id}",
                    amount=unexplained_discrepancy,
                    currency="INR",
                    status="action_required",
                    event_type="settlement.reconciliation",
                )
                db.add(tx)
                db.flush()

                case = RecoveryCase(
                    merchant_id=merchant_id,
                    transaction_id=tx.id,
                    reconciliation_record_id=recon.id,
                    exception_type="reconciliation_variance",
                    status="action_required",
                    stage="reconciliation_discrepancy",
                    amount_at_risk=unexplained_discrepancy,
                    recovery_probability=Decimal("0.70"),
                    priority="HIGH",
                    next_best_action="INVESTIGATE_SETTLEMENT_VARIANCE",
                )
                db.add(case)

        db.commit()
        return records

    def get_settlement_metrics(self, merchant_id: int, db: Session) -> dict[str, Any]:
        """Aggregate exact deterministic KPIs for settlements and reconciliation."""
        settlements = list(db.scalars(select(Settlement).where(Settlement.merchant_id == merchant_id)).all())
        recons = list(db.scalars(select(ReconciliationRecord).where(ReconciliationRecord.merchant_id == merchant_id)).all())

        total_settled = Decimal("0.00")
        amount_failed = Decimal("0.00")
        amount_on_hold = Decimal("0.00")
        failed_count = 0
        hold_count = 0
        processed_count = 0

        for s in settlements:
            if s.status == "processed":
                total_settled += s.amount
                processed_count += 1
            elif s.status == "failed":
                amount_failed += s.amount
                failed_count += 1
            elif s.status == "on_hold":
                amount_on_hold += s.amount
                hold_count += 1

        unexplained_variance = Decimal("0.00")
        unexplained_count = 0
        for r in recons:
            if r.status == "unexplained":
                unexplained_variance += r.discrepancy_amount
                unexplained_count += 1

        return {
            "total_settled_amount": str(total_settled),
            "amount_failed": str(amount_failed),
            "amount_on_hold": str(amount_on_hold),
            "unexplained_reconciliation_variance": str(unexplained_variance),
            "failed_settlement_count": failed_count,
            "on_hold_settlement_count": hold_count,
            "processed_settlement_count": processed_count,
            "unexplained_reconciliation_count": unexplained_count,
            "currency": "INR",
        }

