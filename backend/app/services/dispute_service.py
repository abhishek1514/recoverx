"""Dispute and Chargeback Recovery Workflow Service for RecoverX."""

from __future__ import annotations

import json
import logging
import os
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from fastapi import HTTPException, UploadFile, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.dependencies import verify_merchant_ownership
from app.intelligence.dispute_evidence_engine import (
    calculate_deadline_metrics,
    calculate_dispute_priority,
    evaluate_evidence_completeness,
    get_evidence_requirements,
    validate_document_content_fields,
)
from app.models.audit_log import AuditLog
from app.models.customer import Customer
from app.models.dispute import Dispute
from app.models.document import Document
from app.models.recovery_case import RecoveryCase
from app.models.transaction import Transaction
from app.services.ai_service import generate_dispute_contest_draft
from app.services.document_service import DocumentService
from app.services.razorpay_service import RazorpayService

logger = logging.getLogger(__name__)


class DisputeService:
    def __init__(
        self,
        doc_service: DocumentService | None = None,
        rzp_service: RazorpayService | None = None,
    ) -> None:
        self.doc_service = doc_service or DocumentService()
        self.rzp_service = rzp_service or RazorpayService()

    def get_dispute_or_404(self, dispute_id: int, merchant_id: int, db: Session) -> Dispute:
        """Fetch dispute ensuring tenant ownership."""
        dispute = db.scalar(select(Dispute).where(Dispute.id == dispute_id))
        if dispute is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Dispute not found.")
        verify_merchant_ownership(dispute, merchant_id, "dispute")
        return dispute

    def recalculate_dispute_state(self, dispute: Dispute, db: Session) -> None:
        """Re-evaluate deterministic deadline, evidence completeness, validation, and priority."""
        hours_remaining, deadline_status = calculate_deadline_metrics(dispute.respond_by)
        dispute.deadline_status = deadline_status

        # Get attached documents
        docs = list(db.scalars(select(Document).where(Document.dispute_id == dispute.id)).all())
        doc_types = [doc.document_type for doc in docs]

        completeness, missing_req, missing_rec = evaluate_evidence_completeness(
            dispute.reason_code, doc_types
        )
        dispute.evidence_completeness = completeness

        # Calculate deterministic priority
        dispute.priority = calculate_dispute_priority(
            amount=dispute.amount,
            deadline_status=deadline_status,
            evidence_completeness=completeness,
            status=dispute.status,
            currency=dispute.currency,
        )

        # Update linked recovery case if present
        case = db.scalar(select(RecoveryCase).where(RecoveryCase.dispute_id == dispute.id))
        if case:
            case.priority = dispute.priority
            case.amount_at_risk = dispute.amount
            if dispute.status == "won":
                case.status = "recovered"
                case.recovery_probability = Decimal("1.00")
            elif dispute.status in {"lost", "closed"}:
                case.status = "closed"
                case.recovery_probability = Decimal("0.00")

    def attach_evidence(
        self,
        dispute_id: int,
        merchant_id: int,
        document_type: str,
        file_bytes: bytes,
        filename: str,
        content_type: str | None,
        db: Session,
        extracted_amount: Decimal | None = None,
        extracted_currency: str | None = None,
        extracted_reference: str | None = None,
    ) -> Document:
        """Securely store evidence document and update dispute validation deterministically."""
        dispute = self.get_dispute_or_404(dispute_id, merchant_id, db)

        # Determine recovery case id
        case = db.scalar(select(RecoveryCase).where(RecoveryCase.dispute_id == dispute.id))
        case_id = case.id if case else None

        # Store file in private document storage
        doc = self.doc_service.store_file(
            content=file_bytes,
            filename=filename,
            content_type=content_type,
            recovery_case_id=case_id,
            db=db,
            merchant_id=merchant_id,
            document_type=document_type,
        )
        doc.dispute_id = dispute.id
        doc.file_name = os.path.basename(filename.replace("\\", "/"))
        doc.file_size_bytes = len(file_bytes)

        # Validate document content deterministically if metadata provided
        expected_ref = dispute.payment_id
        val_status, val_notes = validate_document_content_fields(
            dispute_amount=dispute.amount,
            dispute_currency=dispute.currency,
            extracted_amount=extracted_amount,
            extracted_currency=extracted_currency,
            extracted_reference=extracted_reference,
            expected_reference=expected_ref,
        )
        dispute.validation_status = val_status
        dispute.validation_notes = val_notes

        self.recalculate_dispute_state(dispute, db)

        db.add(
            AuditLog(
                merchant_id=merchant_id,
                entity_type="dispute",
                entity_id=dispute.razorpay_dispute_id,
                event_type="evidence_uploaded",
                details=f"Attached evidence '{document_type}' ({filename}). Validation: {val_status}.",
            )
        )
        db.commit()
        db.refresh(doc)
        db.refresh(dispute)
        return doc

    def prepare_contest(
        self,
        dispute_id: int,
        merchant_id: int,
        db: Session,
        merchant_notes: str | None = None,
    ) -> dict[str, Any]:
        """Generate non-authoritative AI contest draft and transition case to ready_for_review."""
        dispute = self.get_dispute_or_404(dispute_id, merchant_id, db)
        self.recalculate_dispute_state(dispute, db)

        tx = db.get(Transaction, dispute.transaction_id) if dispute.transaction_id else None
        customer = db.get(Customer, tx.customer_id) if tx and tx.customer_id else None
        docs = list(db.scalars(select(Document).where(Document.dispute_id == dispute.id)).all())

        draft_result = generate_dispute_contest_draft(
            dispute=dispute,
            transaction=tx,
            customer=customer,
            documents=docs,
            merchant_notes=merchant_notes,
        )

        dispute.contest_summary = draft_result["contest_summary"]
        dispute.contest_status = "ready_for_review"

        db.add(
            AuditLog(
                merchant_id=merchant_id,
                entity_type="dispute",
                entity_id=dispute.razorpay_dispute_id,
                event_type="contest_draft_prepared",
                details=f"Prepared contest draft with status 'ready_for_review'.",
            )
        )
        db.commit()
        db.refresh(dispute)

        return draft_result

    def approve_and_submit_contest(
        self,
        dispute_id: int,
        merchant_id: int,
        db: Session,
        approved_summary: str | None = None,
        user_email: str = "merchant_user",
    ) -> Dispute:
        """Perform merchant-authorized, idempotent contest submission to Razorpay Disputes API."""
        dispute = self.get_dispute_or_404(dispute_id, merchant_id, db)

        # 1. Deadline check
        hours_remaining, deadline_status = calculate_deadline_metrics(dispute.respond_by)
        if deadline_status == "deadline_expired":
            dispute.contest_status = "submission_failed"
            dispute.submission_error = "deadline_expired"
            db.commit()
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Dispute submission deadline has already expired. Cannot submit contest to Razorpay.",
            )

        # 2. Idempotency guard: prevent duplicate submission
        if dispute.contest_status in {"submitted", "under_review"} and dispute.status == "under_review":
            logger.info("Dispute %s contest was already submitted; returning current state.", dispute.razorpay_dispute_id)
            return dispute

        # 3. Final summary selection
        summary_to_send = (approved_summary or dispute.contest_summary or "Contest defense on file.").strip()

        # 4. Gather document references
        docs = list(db.scalars(select(Document).where(Document.dispute_id == dispute.id)).all())
        document_ids = [doc.reference for doc in docs if doc.reference]

        # 5. Execute verified Razorpay API Call
        try:
            self.rzp_service.contest_dispute(
                dispute_id=dispute.razorpay_dispute_id,
                summary=summary_to_send,
                documents=document_ids,
                action="submit",
            )
            dispute.contest_status = "submitted"
            dispute.status = "under_review"
            dispute.contest_summary = summary_to_send
            dispute.contest_submitted_at = datetime.now(UTC)
            dispute.submission_error = None

            # Update linked recovery case
            case = db.scalar(select(RecoveryCase).where(RecoveryCase.dispute_id == dispute.id))
            if case:
                case.status = "merchant_review"
                case.next_best_action = "AWAIT_BANK_REVIEW"

            db.add(
                AuditLog(
                    merchant_id=merchant_id,
                    entity_type="dispute",
                    entity_id=dispute.razorpay_dispute_id,
                    event_type="contest_submitted",
                    details=f"Merchant {user_email} approved and submitted dispute contest to Razorpay.",
                )
            )
            db.commit()
            db.refresh(dispute)
            logger.info("Successfully submitted contest for dispute %s", dispute.razorpay_dispute_id)
            return dispute

        except HTTPException as exc:
            # Categorize safe error without leaking raw secrets
            err_code = "provider_error"
            if exc.status_code == 401 or exc.status_code == 403:
                err_code = "authorization_error"
            elif exc.status_code == 422 or exc.status_code == 400:
                err_code = "invalid_evidence"
            elif exc.status_code == 429:
                err_code = "rate_limited"
            elif exc.status_code >= 500:
                err_code = "temporary_provider_error"

            dispute.contest_status = "submission_failed"
            dispute.submission_error = err_code

            db.add(
                AuditLog(
                    merchant_id=merchant_id,
                    entity_type="dispute",
                    entity_id=dispute.razorpay_dispute_id,
                    event_type="contest_submission_failed",
                    details=f"Contest submission failed with error code '{err_code}'.",
                )
            )
            db.commit()
            raise HTTPException(
                status_code=exc.status_code,
                detail=f"Razorpay contest submission failed: {err_code}. Details: {exc.detail}",
            ) from exc

        except Exception as exc:
            logger.error("Unexpected error submitting contest for dispute %s: %s", dispute.razorpay_dispute_id, exc)
            dispute.contest_status = "submission_failed"
            dispute.submission_error = "unknown_provider_error"
            db.commit()
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Unexpected error communicating with Razorpay. Please retry shortly.",
            ) from exc

    def get_timeline(self, dispute_id: int, merchant_id: int, db: Session) -> list[dict[str, Any]]:
        """Construct audit-friendly chronological timeline of dispute lifecycle events."""
        dispute = self.get_dispute_or_404(dispute_id, merchant_id, db)
        logs = list(
            db.scalars(
                select(AuditLog)
                .where(
                    AuditLog.merchant_id == merchant_id,
                    AuditLog.entity_id.in_([str(dispute.id), dispute.razorpay_dispute_id]),
                )
                .order_by(AuditLog.created_at.asc())
            ).all()
        )

        timeline = [
            {
                "event": "dispute_received",
                "title": "Dispute Received from Bank",
                "description": f"Chargeback dispute raised for {dispute.amount} {dispute.currency} (Reason: {dispute.reason_code or 'general'}).",
                "timestamp": dispute.created_at.isoformat() if dispute.created_at else datetime.now(UTC).isoformat(),
                "status": "completed",
            }
        ]

        for log in logs:
            timeline.append(
                {
                    "event": log.event_type,
                    "title": log.event_type.replace("_", " ").title(),
                    "description": log.details,
                    "timestamp": log.created_at.isoformat(),
                    "status": "completed",
                }
            )

        if dispute.status == "won":
            timeline.append(
                {
                    "event": "dispute_won",
                    "title": "Dispute Won",
                    "description": f"Bank accepted contest evidence. Recovered {dispute.amount} {dispute.currency}.",
                    "timestamp": dispute.updated_at.isoformat() if dispute.updated_at else datetime.now(UTC).isoformat(),
                    "status": "completed",
                }
            )
        elif dispute.status == "lost":
            timeline.append(
                {
                    "event": "dispute_lost",
                    "title": "Dispute Lost",
                    "description": "Bank ruled in favor of cardholder.",
                    "timestamp": dispute.updated_at.isoformat() if dispute.updated_at else datetime.now(UTC).isoformat(),
                    "status": "completed",
                }
            )

        return timeline

    def get_metrics_summary(self, merchant_id: int, db: Session) -> dict[str, Any]:
        """Calculate exact deterministic metrics for dispute recovery."""
        disputes = list(db.scalars(select(Dispute).where(Dispute.merchant_id == merchant_id)).all())

        total_disputed = Decimal("0.00")
        amount_at_risk = Decimal("0.00")
        amount_contested = Decimal("0.00")
        amount_recovered = Decimal("0.00")
        amount_lost = Decimal("0.00")

        open_count = 0
        critical_count = 0
        complete_count = 0
        won_count = 0
        lost_count = 0

        for d in disputes:
            total_disputed += d.amount
            if d.status in {"open", "action_required", "under_review"}:
                open_count += 1
                amount_at_risk += d.amount
                if d.deadline_status == "deadline_critical":
                    critical_count += 1
                if d.evidence_completeness == "complete":
                    complete_count += 1
            if d.contest_status in {"submitted", "under_review"}:
                amount_contested += d.amount
            if d.status == "won":
                won_count += 1
                amount_recovered += d.amount
            elif d.status in {"lost", "closed"}:
                lost_count += 1
                amount_lost += d.amount

        evidence_complete_rate = round((complete_count / open_count * 100.0), 1) if open_count > 0 else 100.0
        resolved_total = won_count + lost_count
        contest_success_rate = round((won_count / resolved_total * 100.0), 1) if resolved_total > 0 else 0.0

        return {
            "total_disputed_amount": str(total_disputed),
            "amount_at_risk": str(amount_at_risk),
            "amount_contested": str(amount_contested),
            "amount_recovered": str(amount_recovered),
            "amount_lost": str(amount_lost),
            "open_disputes": open_count,
            "deadline_critical_disputes": critical_count,
            "evidence_complete_rate": evidence_complete_rate,
            "contest_success_rate": contest_success_rate,
            "currency": "INR",
        }

