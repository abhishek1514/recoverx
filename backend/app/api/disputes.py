"""Disputes API endpoints for RecoverX revenue exception recovery."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.dependencies import get_current_merchant, get_current_user, verify_merchant_ownership
from app.database.session import get_db
from app.intelligence.dispute_evidence_engine import (
    calculate_deadline_metrics,
    evaluate_evidence_completeness,
    get_evidence_requirements,
)
from app.models.audit_log import AuditLog
from app.models.dispute import Dispute
from app.models.document import Document
from app.models.merchant import Merchant
from app.models.user import User
from app.schemas.dispute import (
    DisputeContestApproveRequest,
    DisputeContestDraftRequest,
    DisputeContestDraftResponse,
    DisputeContestRequest,
    DisputeEvidenceItem,
    DisputeEvidenceResponse,
    DisputeMetricsResponse,
    DisputeRead,
    DisputeTimelineEvent,
)
from app.services.dispute_service import DisputeService
from app.services.razorpay_service import RazorpayService

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/disputes", tags=["disputes"])


def _hydrate_dispute_read(dispute: Dispute) -> DisputeRead:
    hours_rem, deadline_st = calculate_deadline_metrics(dispute.respond_by)
    data = {
        "id": dispute.id,
        "merchant_id": dispute.merchant_id,
        "transaction_id": dispute.transaction_id,
        "razorpay_dispute_id": dispute.razorpay_dispute_id,
        "payment_id": dispute.payment_id,
        "amount": dispute.amount,
        "currency": dispute.currency,
        "reason_code": dispute.reason_code,
        "status": dispute.status,
        "phase": dispute.phase,
        "respond_by": dispute.respond_by,
        "deducted_at": dispute.deducted_at,
        "evidence_submitted_at": dispute.evidence_submitted_at,
        "priority": dispute.priority or "MEDIUM",
        "deadline_status": deadline_st,
        "hours_remaining": hours_rem,
        "contest_status": dispute.contest_status or "draft",
        "contest_summary": dispute.contest_summary,
        "contest_submitted_at": dispute.contest_submitted_at,
        "submission_error": dispute.submission_error,
        "evidence_completeness": dispute.evidence_completeness or "incomplete",
        "validation_status": dispute.validation_status or "pending",
        "validation_notes": dispute.validation_notes,
        "created_at": dispute.created_at,
        "updated_at": dispute.updated_at,
    }
    return DisputeRead.model_validate(data)


@router.get("/metrics/summary", response_model=DisputeMetricsResponse)
def get_dispute_metrics(
    current_merchant: Merchant = Depends(get_current_merchant),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Retrieve aggregate deterministic recovery metrics for the merchant."""
    service = DisputeService()
    return service.get_metrics_summary(current_merchant.id, db)


@router.get("", response_model=list[DisputeRead])
def list_disputes(
    status: str | None = None,
    current_merchant: Merchant = Depends(get_current_merchant),
    db: Session = Depends(get_db),
) -> list[DisputeRead]:
    """List all disputes for the authenticated merchant with computed deadline metrics."""
    query = select(Dispute).where(Dispute.merchant_id == current_merchant.id)
    if status:
        query = query.where(Dispute.status == status.lower().strip())
    query = query.order_by(Dispute.created_at.desc())
    disputes = list(db.scalars(query).all())
    return [_hydrate_dispute_read(d) for d in disputes]


@router.get("/{dispute_id}", response_model=DisputeRead)
def get_dispute(
    dispute_id: int,
    current_merchant: Merchant = Depends(get_current_merchant),
    db: Session = Depends(get_db),
) -> DisputeRead:
    """Get single dispute details ensuring merchant tenancy."""
    service = DisputeService()
    dispute = service.get_dispute_or_404(dispute_id, current_merchant.id, db)
    service.recalculate_dispute_state(dispute, db)
    db.commit()
    return _hydrate_dispute_read(dispute)


@router.get("/{dispute_id}/evidence", response_model=DisputeEvidenceResponse)
def get_dispute_evidence(
    dispute_id: int,
    current_merchant: Merchant = Depends(get_current_merchant),
    db: Session = Depends(get_db),
) -> DisputeEvidenceResponse:
    """Get deterministic evidence checklist and uploaded documents for a dispute."""
    service = DisputeService()
    dispute = service.get_dispute_or_404(dispute_id, current_merchant.id, db)
    service.recalculate_dispute_state(dispute, db)
    db.commit()

    reqs = get_evidence_requirements(dispute.reason_code)
    docs = list(db.scalars(select(Document).where(Document.dispute_id == dispute.id)).all())

    doc_types = [d.document_type for d in docs]
    completeness, missing_req, missing_rec = evaluate_evidence_completeness(
        dispute.reason_code, doc_types
    )

    submitted_items = [
        DisputeEvidenceItem(
            id=d.id,
            document_type=d.document_type,
            file_name=d.file_name or "document",
            file_size_bytes=d.file_size_bytes or 0,
            reference=d.reference,
            status=d.status,
            created_at=d.created_at,
        )
        for d in docs
    ]

    return DisputeEvidenceResponse(
        dispute_id=dispute.id,
        reason_code=dispute.reason_code or "general",
        required_evidence=reqs["required"],
        recommended_evidence=reqs["recommended"],
        submitted_documents=submitted_items,
        evidence_completeness=completeness,
        missing_required=missing_req,
        missing_recommended=missing_rec,
        validation_status=dispute.validation_status or "pending",
        validation_notes=dispute.validation_notes,
    )


@router.post("/{dispute_id}/evidence", response_model=DisputeEvidenceItem)
async def upload_dispute_evidence(
    dispute_id: int,
    document_type: str = Form(..., description="Evidence category (e.g. proof_of_delivery, invoice)"),
    file: UploadFile = File(..., description="Document file to attach"),
    extracted_amount: str | None = Form(None, description="Optional extracted invoice amount for deterministic validation"),
    extracted_currency: str | None = Form(None, description="Optional extracted currency"),
    extracted_reference: str | None = Form(None, description="Optional extracted reference"),
    current_merchant: Merchant = Depends(get_current_merchant),
    db: Session = Depends(get_db),
) -> DisputeEvidenceItem:
    """Securely upload and link evidence document to a dispute with magic-byte validation."""
    service = DisputeService()
    content = await file.read()

    amount_val = Decimal(extracted_amount) if extracted_amount and extracted_amount.strip() else None

    doc = service.attach_evidence(
        dispute_id=dispute_id,
        merchant_id=current_merchant.id,
        document_type=document_type.strip().lower(),
        file_bytes=content,
        filename=file.filename or "evidence.pdf",
        content_type=file.content_type,
        db=db,
        extracted_amount=amount_val,
        extracted_currency=extracted_currency,
        extracted_reference=extracted_reference,
    )

    return DisputeEvidenceItem(
        id=doc.id,
        document_type=doc.document_type,
        file_name=doc.file_name,
        file_size_bytes=doc.file_size_bytes,
        reference=doc.reference,
        status=doc.status,
        created_at=doc.created_at,
    )


@router.post("/{dispute_id}/prepare-contest", response_model=DisputeContestDraftResponse)
def prepare_dispute_contest(
    dispute_id: int,
    payload: DisputeContestDraftRequest | None = None,
    current_merchant: Merchant = Depends(get_current_merchant),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Generate non-authoritative AI contest defense draft and explanations with PII protection."""
    service = DisputeService()
    notes = payload.merchant_notes if payload else None
    return service.prepare_contest(dispute_id, current_merchant.id, db, merchant_notes=notes)


@router.post("/{dispute_id}/approve-contest", response_model=DisputeRead)
def approve_and_submit_dispute_contest(
    dispute_id: int,
    payload: DisputeContestApproveRequest | None = None,
    current_user: User = Depends(get_current_user),
    current_merchant: Merchant = Depends(get_current_merchant),
    db: Session = Depends(get_db),
) -> DisputeRead:
    """Merchant approves and triggers idempotent contest submission to Razorpay Disputes API."""
    service = DisputeService()
    approved_summary = payload.approved_summary if payload else None
    dispute = service.approve_and_submit_contest(
        dispute_id=dispute_id,
        merchant_id=current_merchant.id,
        db=db,
        approved_summary=approved_summary,
        user_email=current_user.email,
    )
    return _hydrate_dispute_read(dispute)


@router.post("/{dispute_id}/contest", response_model=DisputeRead)
def contest_dispute(
    dispute_id: int,
    payload: DisputeContestRequest,
    current_merchant: Merchant = Depends(get_current_merchant),
    db: Session = Depends(get_db),
) -> DisputeRead:
    """Submit contest evidence for a dispute via Razorpay Disputes API."""
    service = DisputeService()
    dispute = service.approve_and_submit_contest(
        dispute_id=dispute_id,
        merchant_id=current_merchant.id,
        db=db,
        approved_summary=payload.summary,
    )
    return _hydrate_dispute_read(dispute)


@router.get("/{dispute_id}/timeline", response_model=list[DisputeTimelineEvent])
def get_dispute_timeline(
    dispute_id: int,
    current_merchant: Merchant = Depends(get_current_merchant),
    db: Session = Depends(get_db),
) -> list[dict[str, Any]]:
    """Retrieve chronological audit timeline for the dispute."""
    service = DisputeService()
    return service.get_timeline(dispute_id, current_merchant.id, db)
