import json
import logging
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.ai.schemas import CaseAIAnalysisResponse
from app.core.config import get_settings
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
from app.schemas.case import RecoveryCaseRead
from app.schemas.recovery import (
    AuditLogRead,
    CaseAnalysisRead,
    CaseResolutionDetails,
    MerchantReviewRequest,
    MerchantReviewResponse,
    ValidationCheckRead,
    ValidationResponse,
)
from app.services.ai_service import generate_case_explanation
from app.services.recovery_service import analyze_transaction
from app.validation.deterministic_rules import validate_recovery_submission

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/cases", tags=["cases"])


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


def _case_response(db: Session, recovery_case: RecoveryCase) -> CaseAnalysisRead:
    transaction = db.get(Transaction, recovery_case.transaction_id)
    assessment = db.scalar(
        select(RiskAssessment)
        .where(RiskAssessment.transaction_id == recovery_case.transaction_id)
        .order_by(RiskAssessment.id.desc())
    )
    action = db.scalar(
        select(Action).where(Action.recovery_case_id == recovery_case.id).order_by(Action.id.desc())
    )
    if transaction is None or assessment is None or action is None:
        raise HTTPException(status_code=500, detail="Case analysis data is incomplete")
    return CaseAnalysisRead(
        case_id=recovery_case.id,
        transaction={
            "id": transaction.id,
            "payment_id": transaction.external_id,
            "order_id": transaction.order_id,
            "amount": str(transaction.amount),
            "currency": transaction.currency,
            "status": transaction.status,
            "country_code": transaction.country_code or "IN",
        },
        is_high_value=transaction.amount >= get_settings().get_high_value_threshold(transaction.currency),
        risk_score=assessment.risk_score or assessment.settlement_risk_score or 0,
        readiness_status=assessment.readiness_status or assessment.status,
        risk_reasons=json.loads(assessment.risk_reasons or "[]"),
        missing_information=json.loads(assessment.missing_information or "[]"),
        revenue_at_risk=recovery_case.amount_at_risk or 0,
        recovery_probability=recovery_case.recovery_probability or 0,
        next_best_action=recovery_case.next_best_action or action.action_type,
        action_reason=action.reason or action.details or "",
        case_status=recovery_case.status,
        analyzed_at=assessment.created_at,
    )


@router.post("/analyze/{transaction_id}", response_model=CaseAnalysisRead, status_code=status.HTTP_200_OK)
def analyze_case(
    transaction_id: int,
    db: Session = Depends(get_db),
    merchant: Merchant = Depends(get_current_merchant),
) -> CaseAnalysisRead:
    transaction = db.get(Transaction, transaction_id)
    if transaction is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Transaction not found")
    verify_merchant_ownership(transaction, merchant.id, "Transaction")

    recovery_case = analyze_transaction(transaction_id, db)
    return _case_response(db, recovery_case)


@router.post("/{case_id}/ai-analysis", response_model=CaseAIAnalysisResponse, status_code=status.HTTP_200_OK)
def analyze_case_with_ai(
    case_id: int,
    db: Session = Depends(get_db),
    merchant: Merchant = Depends(get_current_merchant),
) -> CaseAIAnalysisResponse:
    case = db.get(RecoveryCase, case_id)
    if case is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Recovery case not found")
    verify_merchant_ownership(case, merchant.id, "Recovery Case")

    return generate_case_explanation(case_id, db, merchant_id=merchant.id)


@router.post("/{case_id}/validate", response_model=ValidationResponse, status_code=status.HTTP_200_OK)
def trigger_case_validation(
    case_id: int,
    db: Session = Depends(get_db),
    merchant: Merchant = Depends(get_current_merchant),
) -> ValidationResponse:
    """Run on-demand deterministic validation for an active recovery case."""
    case = db.get(RecoveryCase, case_id)
    if case is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Recovery case not found")
    verify_merchant_ownership(case, merchant.id, "Recovery Case")

    transaction = db.get(Transaction, case.transaction_id)
    if transaction is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Transaction not found")

    customer = db.get(Customer, case.customer_id) if case.customer_id else None

    # Retrieve last customer submission payload from audit log
    last_response_log = db.scalar(
        select(AuditLog)
        .where(
            AuditLog.entity_id == str(case.id),
            AuditLog.event_type == "customer_response_received",
        )
        .order_by(AuditLog.id.desc())
    )
    submission_data = json.loads(last_response_log.details or "{}") if last_response_log else {}

    if not submission_data.get("invoice_amount"):
        submission_data["invoice_amount"] = str(transaction.amount)
    if not submission_data.get("invoice_currency"):
        submission_data["invoice_currency"] = transaction.currency
    if not submission_data.get("invoice_reference"):
        submission_data["invoice_reference"] = transaction.external_id or f"inv_{case.id}"

    val_result = validate_recovery_submission(
        case=case,
        transaction=transaction,
        customer=customer,
        submission_data=submission_data,
        db=db,
    )

    validation_record = ValidationResult(
        recovery_case_id=case.id,
        validation_type="deterministic_reconciliation",
        passed=(val_result["status"] == "PASS"),
        details=json.dumps(val_result),
    )
    db.add(validation_record)

    if val_result["status"] == "PASS":
        case.status = "settlement_ready"
        case.stage = "settlement_ready"
        _audit(db, "recovery_case", str(case.id), "settlement_ready", "Case verified and settlement-ready.", merchant_id=merchant.id)
    elif val_result["status"] == "FAIL":
        case.status = "validation_failed"
        case.stage = "action_required"
        _audit(db, "recovery_case", str(case.id), "validation_failed", val_result["overall_reason"], merchant_id=merchant.id)
    else:
        case.status = "merchant_review"
        case.stage = "merchant_review"
        _audit(db, "recovery_case", str(case.id), "merchant_review", val_result["overall_reason"], merchant_id=merchant.id)

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


@router.post("/{case_id}/review", response_model=MerchantReviewResponse, status_code=status.HTTP_200_OK)
def review_case_decision(
    case_id: int,
    payload: MerchantReviewRequest,
    db: Session = Depends(get_db),
    merchant: Merchant = Depends(get_current_merchant),
) -> MerchantReviewResponse:
    """Record merchant decision for the recovery workflow."""
    case = db.get(RecoveryCase, case_id)
    if case is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Recovery case not found")
    verify_merchant_ownership(case, merchant.id, "Recovery Case")

    decision = payload.decision.upper().strip()
    if decision not in {"APPROVE", "REQUEST_MORE_INFORMATION", "REJECT"}:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid merchant decision '{decision}'. Allowed: APPROVE, REQUEST_MORE_INFORMATION, REJECT",
        )

    if decision == "APPROVE":
        case.status = "recovered"
        case.stage = "recovered"
        event_type = "merchant_approved"
        detail_msg = payload.notes or "Merchant approved case for workflow completion (recovered/unlocked)."
    elif decision == "REQUEST_MORE_INFORMATION":
        case.status = "action_required"
        case.stage = "action_required"
        event_type = "merchant_requested_info"
        detail_msg = payload.notes or "Merchant requested additional customer clarification."
    else:
        case.status = "closed"
        case.stage = "closed"
        event_type = "merchant_rejected"
        detail_msg = payload.notes or "Merchant rejected resolution; case closed."

    db.add(
        Action(
            recovery_case_id=case.id,
            action_type=f"MERCHANT_REVIEW_{decision}",
            status="completed",
            details=payload.notes,
            reason=detail_msg,
            confidence=Decimal("1.00"),
        )
    )

    _audit(
        db,
        "recovery_case",
        str(case.id),
        event_type,
        detail_msg,
        merchant_id=merchant.id,
    )
    db.commit()
    db.refresh(case)

    return MerchantReviewResponse(
        case_id=case.id,
        decision=decision,
        case_status=case.status,
        case_stage=case.stage,
        notes=payload.notes,
        reviewed_at=datetime.now(UTC),
    )


@router.get("/{case_id}/resolution", response_model=CaseResolutionDetails)
def get_case_resolution(
    case_id: int,
    db: Session = Depends(get_db),
    merchant: Merchant = Depends(get_current_merchant),
) -> CaseResolutionDetails:
    """Return all customer resolution context, documents, validation results, and merchant review."""
    case = db.get(RecoveryCase, case_id)
    if case is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Recovery case not found")
    verify_merchant_ownership(case, merchant.id, "Recovery Case")

    req_action = db.scalar(
        select(Action)
        .where(
            Action.recovery_case_id == case.id,
            Action.action_type == "CUSTOMER_RESOLUTION_REQUESTED",
        )
        .order_by(Action.id.desc())
    )
    req_data = json.loads(req_action.details or "{}") if req_action else {}

    cust_log = db.scalar(
        select(AuditLog)
        .where(
            AuditLog.entity_id == str(case.id),
            AuditLog.event_type == "customer_response_received",
        )
        .order_by(AuditLog.id.desc())
    )
    cust_submission = json.loads(cust_log.details or "{}") if cust_log else None

    docs = db.scalars(select(Document).where(Document.recovery_case_id == case.id)).all()
    doc_list = [{"id": d.id, "type": d.document_type, "reference": d.reference, "status": d.status} for d in docs]

    val_rec = db.scalar(
        select(ValidationResult).where(ValidationResult.recovery_case_id == case.id).order_by(ValidationResult.id.desc())
    )
    val_data = json.loads(val_rec.details or "{}") if val_rec else None

    merchant_action = db.scalar(
        select(Action)
        .where(
            Action.recovery_case_id == case.id,
            Action.action_type.like("MERCHANT_REVIEW_%"),
        )
        .order_by(Action.id.desc())
    )
    merchant_data = (
        {
            "action": merchant_action.action_type,
            "details": merchant_action.details,
            "reason": merchant_action.reason,
            "created_at": merchant_action.created_at.isoformat(),
        }
        if merchant_action
        else None
    )

    return CaseResolutionDetails(
        case_id=case.id,
        case_status=case.status,
        case_stage=case.stage,
        next_best_action=case.next_best_action,
        requested_information=req_data.get("requested_information", []),
        requested_document_type=req_data.get("requested_document_type"),
        customer_message=req_data.get("customer_message"),
        customer_submission=cust_submission,
        documents=doc_list,
        latest_validation=val_data,
        merchant_decision=merchant_data,
    )


@router.get("/{case_id}/audit", response_model=list[AuditLogRead])
def get_case_audit_trail(
    case_id: int,
    db: Session = Depends(get_db),
    merchant: Merchant = Depends(get_current_merchant),
) -> list[AuditLog]:
    """Retrieve full audit log trail for a recovery case."""
    case = db.get(RecoveryCase, case_id)
    if case is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Recovery case not found")
    verify_merchant_ownership(case, merchant.id, "Recovery Case")

    logs = db.scalars(
        select(AuditLog)
        .where(
            or_(
                (AuditLog.entity_id == str(case.id)),
                (AuditLog.entity_id == str(case.transaction_id)),
            )
        )
        .order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
    ).all()
    return logs


@router.get("/{case_id}", response_model=CaseAnalysisRead)
def get_case(
    case_id: int,
    db: Session = Depends(get_db),
    merchant: Merchant = Depends(get_current_merchant),
) -> CaseAnalysisRead:
    recovery_case = db.get(RecoveryCase, case_id)
    if recovery_case is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Recovery case not found")
    verify_merchant_ownership(recovery_case, merchant.id, "Recovery Case")
    return _case_response(db, recovery_case)


@router.get("", response_model=list[RecoveryCaseRead])
def list_cases(
    db: Session = Depends(get_db),
    merchant: Merchant = Depends(get_current_merchant),
) -> list[RecoveryCase]:
    """Return recovery orchestration cases scoped to current merchant."""
    cases = db.scalars(
        select(RecoveryCase)
        .where(or_(RecoveryCase.merchant_id == merchant.id, RecoveryCase.merchant_id.is_(None)))
        .order_by(RecoveryCase.created_at.desc())
    ).all()
    logger.info("Listed %s recovery cases for merchant %s", len(cases), merchant.id)
    return cases
