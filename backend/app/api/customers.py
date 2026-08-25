"""Customer resolution API routes for the RecoverX recovery workflow."""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.dependencies import get_current_merchant, verify_merchant_ownership
from app.database.session import get_db
from app.models.action import Action
from app.models.audit_log import AuditLog
from app.models.customer import Customer
from app.models.document import Document
from app.models.merchant import Merchant
from app.models.recovery_case import RecoveryCase
from app.models.risk_assessment import RiskAssessment
from app.models.transaction import Transaction
from app.models.validation import ValidationResult
from app.schemas.recovery import (
    CustomerResolveRequest,
    ResolutionRequestResponse,
    ValidationCheckRead,
    ValidationResponse,
)
from app.services.document_service import DocumentService
from app.services.notification_service import NotificationService
from app.validation.deterministic_rules import validate_recovery_submission

logger = logging.getLogger(__name__)
router = APIRouter(tags=["customers"])


def _audit(db: Session, entity_type: str, entity_id: str, event_type: str, details: str, merchant_id: int = 1) -> None:
    db.add(
        AuditLog(
            merchant_id=merchant_id,
            entity_type=entity_type,
            entity_id=entity_id,
            event_type=event_type,
            details=details,
        )
    )


@router.post("/api/cases/{case_id}/request-resolution", response_model=ResolutionRequestResponse, status_code=status.HTTP_200_OK)
def request_case_resolution(
    case_id: int,
    db: Session = Depends(get_db),
    merchant: Merchant = Depends(get_current_merchant),
) -> ResolutionRequestResponse:
    """Initiate a customer resolution request based on deterministic intelligence."""
    case = db.get(RecoveryCase, case_id)
    if case is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Recovery case not found")
    verify_merchant_ownership(case, merchant.id, "Recovery Case")

    transaction = db.get(Transaction, case.transaction_id)
    if transaction is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Transaction not found")

    assessment = db.scalar(
        select(RiskAssessment).where(RiskAssessment.transaction_id == case.transaction_id).order_by(RiskAssessment.id.desc())
    )
    missing_info = json.loads(assessment.missing_information or "[]") if assessment else []
    customer = db.get(Customer, case.customer_id) if case.customer_id else None

    notification = NotificationService.create_resolution_notification(
        case=case,
        transaction=transaction,
        customer=customer,
        missing_information=missing_info,
        next_best_action=case.next_best_action or "REQUEST_INFORMATION",
    )

    # Transition case to action_required
    case.status = "action_required"
    case.stage = "action_required"

    # Record action
    db.add(Action(
        recovery_case_id=case.id,
        action_type="CUSTOMER_RESOLUTION_REQUESTED",
        status="requested",
        details=json.dumps(notification, default=str),
        reason=notification["customer_message"],
        confidence=Decimal("0.90"),
    ))

    _audit(
        db,
        "recovery_case",
        str(case.id),
        "resolution_requested",
        f"Resolution requested for {len(notification['requested_information'])} item(s).",
        merchant_id=merchant.id,
    )
    db.commit()
    db.refresh(case)

    return ResolutionRequestResponse(
        case_id=case.id,
        requested_information=notification["requested_information"],
        requested_document_type=notification["requested_document_type"],
        customer_message=notification["customer_message"],
        status="action_required",
        created_at=notification["created_at"],
    )


@router.post("/api/customers/cases/{case_id}/resolve", response_model=ValidationResponse, status_code=status.HTTP_200_OK)
async def resolve_case(
    case_id: int,
    request: Request,
    db: Session = Depends(get_db),
) -> ValidationResponse:
    """Accept customer submission (JSON or multipart form), store documents, and run validation."""
    case = db.get(RecoveryCase, case_id)
    if case is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Recovery case not found")

    transaction = db.get(Transaction, case.transaction_id)
    if transaction is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Transaction not found")

    merchant_id = case.merchant_id or 1
    content_type = request.headers.get("content-type", "").lower()
    submission_dict: dict[str, Any] = {}
    uploaded_file_bytes: bytes | None = None
    uploaded_filename: str | None = None
    uploaded_file_mime: str | None = None

    if "multipart/form-data" in content_type or "application/x-www-form-urlencoded" in content_type:
        form = await request.form()
        submission_dict = {
            "customer_name": form.get("customer_name"),
            "customer_email": form.get("customer_email"),
            "country_code": form.get("country_code"),
            "invoice_amount": form.get("invoice_amount"),
            "invoice_currency": form.get("invoice_currency"),
            "invoice_reference": form.get("invoice_reference") or form.get("invoice_id"),
            "invoice_date": form.get("invoice_date"),
            "notes": form.get("notes"),
        }
        file_obj = form.get("file")
        if file_obj and hasattr(file_obj, "filename") and file_obj.filename:
            uploaded_filename = file_obj.filename
            uploaded_file_mime = getattr(file_obj, "content_type", None)
            uploaded_file_bytes = await file_obj.read()
    else:
        try:
            body = await request.json()
            if isinstance(body, dict):
                submission_dict = body
        except Exception:
            submission_dict = {}

    # Update or associate customer
    customer = db.get(Customer, case.customer_id) if case.customer_id else None
    if customer is None and (submission_dict.get("customer_email") or submission_dict.get("customer_name")):
        customer = Customer(
            external_id=f"cust_{case_id}_{int(datetime.now(UTC).timestamp())}",
            name=submission_dict.get("customer_name"),
            email=submission_dict.get("customer_email"),
            country_code=submission_dict.get("country_code"),
        )
        db.add(customer)
        db.flush()
        case.customer_id = customer.id
        transaction.customer_id = customer.id
    elif customer:
        if submission_dict.get("customer_name"):
            customer.name = str(submission_dict["customer_name"])
        if submission_dict.get("customer_email"):
            customer.email = str(submission_dict["customer_email"])
        if submission_dict.get("country_code"):
            customer.country_code = str(submission_dict["country_code"])

    # Store uploaded document if present
    if uploaded_file_bytes and uploaded_filename:
        doc_service = DocumentService()
        doc_service.store_file(
            content=uploaded_file_bytes,
            filename=uploaded_filename,
            content_type=uploaded_file_mime,
            recovery_case_id=case.id,
            db=db,
            merchant_id=merchant_id,
            document_type="invoice",
        )

    # Record customer submission in AuditLog and Action
    _audit(
        db,
        "recovery_case",
        str(case.id),
        "customer_response_received",
        json.dumps({k: str(v) for k, v in submission_dict.items() if v is not None and k not in {"password", "cvv"}}),
        merchant_id=merchant_id,
    )

    case.status = "customer_responded"
    case.stage = "validation_pending"
    db.commit()

    # Run authoritative deterministic validation
    val_result = validate_recovery_submission(
        case=case,
        transaction=transaction,
        customer=customer,
        submission_data=submission_dict,
        db=db,
    )

    validation_record = ValidationResult(
        recovery_case_id=case.id,
        validation_type="deterministic_reconciliation",
        passed=(val_result["status"] == "PASS"),
        details=json.dumps(val_result),
    )
    db.add(validation_record)

    # Safe state transitions based on deterministic outcome
    if val_result["status"] == "PASS":
        case.status = "settlement_ready"
        case.stage = "settlement_ready"
        _audit(db, "recovery_case", str(case.id), "settlement_ready", "Case reached settlement readiness following passing validation.", merchant_id=merchant_id)
    elif val_result["status"] == "FAIL":
        case.status = "validation_failed"
        case.stage = "action_required"
        _audit(db, "recovery_case", str(case.id), "validation_failed", val_result["overall_reason"], merchant_id=merchant_id)
    else:  # REVIEW
        case.status = "merchant_review"
        case.stage = "merchant_review"
        _audit(db, "recovery_case", str(case.id), "merchant_review", val_result["overall_reason"], merchant_id=merchant_id)

    db.commit()
    db.refresh(case)

    return ValidationResponse(
        case_id=case.id,
        status=val_result["status"],
        checks=[
            ValidationCheckRead(name=c["name"], status=c["status"], message=c["message"])
            for c in val_result["checks"]
        ],
        overall_reason=val_result["overall_reason"],
        validated_at=datetime.now(UTC),
    )


@router.get("/api/documents/{doc_id}/download")
def download_document(
    doc_id: int,
    token: str = Query(..., description="Short-lived HMAC signed download token"),
    db: Session = Depends(get_db),
    merchant: Merchant = Depends(get_current_merchant),
) -> FileResponse:
    """Download private document using verified signed token and merchant tenant authorization."""
    doc_service = DocumentService()
    file_path, media_type = doc_service.retrieve_file(doc_id=doc_id, token=token, merchant_id=merchant.id, db=db)
    return FileResponse(path=file_path, media_type=media_type, filename=file_path.name)


@router.get("/api/documents/{doc_id}/signed-url")
def get_document_signed_url(
    doc_id: int,
    db: Session = Depends(get_db),
    merchant: Merchant = Depends(get_current_merchant),
) -> dict[str, str]:
    """Generate a time-limited signed URL for private document download."""
    doc = db.get(Document, doc_id)
    if not doc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found.")
    verify_merchant_ownership(doc, merchant.id, "Document")

    doc_service = DocumentService()
    url = doc_service.get_signed_download_url(doc_id=doc_id, merchant_id=merchant.id)
    return {"download_url": url, "expires_in_seconds": "300"}
