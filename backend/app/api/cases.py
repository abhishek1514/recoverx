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
    customer = db.get(Customer, recovery_case.customer_id) if recovery_case.customer_id else None
    validation = db.scalar(
        select(ValidationResult)
        .where(ValidationResult.recovery_case_id == recovery_case.id)
        .order_by(ValidationResult.id.desc())
    )
    docs = db.scalars(select(Document).where(Document.recovery_case_id == recovery_case.id)).all()
    doc_list = [{"id": d.id, "type": d.document_type, "reference": d.reference, "status": d.status} for d in docs]
    actions = db.scalars(select(Action).where(Action.recovery_case_id == recovery_case.id)).all()
    action_list = [{"id": a.id, "type": a.action_type, "status": a.status, "reason": a.reason} for a in actions]

    currency = transaction.currency if transaction else "INR"
    threshold = get_settings().get_high_value_threshold(currency)
    amount = transaction.amount if transaction else Decimal("0.00")
    is_high_value = amount >= threshold

    val_data = None
    if validation and validation.details:
        try:
            val_data = json.loads(validation.details)
        except Exception:
            val_data = None

    tx_data = {
        "id": transaction.id if transaction else recovery_case.transaction_id,
        "amount": amount,
        "currency": currency,
        "status": transaction.status if transaction else "unknown",
        "order_id": transaction.order_id if transaction else None,
        "payment_id": transaction.external_id if transaction else None,
        "customer_id": customer.external_id if customer else None,
        "customer_name": customer.name if customer else None,
        "customer_email": customer.email if customer else None,
    }

    r_score = Decimal(str(assessment.risk_score)) if (assessment and assessment.risk_score is not None) else Decimal("0.00")
    r_reasons = json.loads(assessment.risk_reasons or "[]") if assessment else []
    missing_info = json.loads(assessment.missing_information or "[]") if assessment else []
    rev_at_risk = recovery_case.amount_at_risk or Decimal("0.00")
    rec_prob = recovery_case.recovery_probability or (Decimal(str(assessment.confidence)) if assessment and assessment.confidence is not None else Decimal("0.000"))
    nba = recovery_case.next_best_action or (assessment.suggested_action if assessment else "REQUEST_INFORMATION")
    act_reason = assessment.suggested_action if assessment else "Deterministic rule evaluation"
    analyzed_ts = assessment.created_at if assessment and assessment.created_at else (recovery_case.created_at or datetime.now(UTC))

    return CaseAnalysisRead(
        case_id=recovery_case.id,
        transaction=tx_data,
        is_high_value=is_high_value,
        risk_score=r_score,
        readiness_status=assessment.readiness_status if assessment else "ready_for_review",
        risk_reasons=r_reasons,
        missing_information=missing_info,
        revenue_at_risk=rev_at_risk,
        recovery_probability=rec_prob,
        next_best_action=nba,
        action_reason=act_reason,
        case_status=recovery_case.status,
        analyzed_at=analyzed_ts,
    )


@router.post("/analyze/{transaction_id}", response_model=CaseAnalysisRead, status_code=status.HTTP_200_OK)
def trigger_analysis(
    transaction_id: int,
    db: Session = Depends(get_db),
    merchant: Merchant = Depends(get_current_merchant),
) -> CaseAnalysisRead:
    tx = db.get(Transaction, transaction_id)
    if tx is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Transaction not found")
    verify_merchant_ownership(tx, merchant.id, "Transaction")

    recovery_case = analyze_transaction(transaction_id, db)
    return _case_response(db, recovery_case)


@router.post("/{case_id}/ai-analysis", response_model=CaseAIAnalysisResponse, status_code=status.HTTP_200_OK)
def get_case_ai_analysis(
    case_id: int,
    db: Session = Depends(get_db),
    merchant: Merchant = Depends(get_current_merchant),
) -> CaseAIAnalysisResponse:
    """Generate advisory AI analysis for a case ensuring tenant ownership."""
    recovery_case = db.get(RecoveryCase, case_id)
    if recovery_case is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Recovery case not found")
    verify_merchant_ownership(recovery_case, merchant.id, "Recovery Case")

    return generate_case_explanation(case_id, db)


@router.post("/{case_id}/validate", response_model=ValidationResponse, status_code=status.HTTP_200_OK)
def run_case_validation(
    case_id: int,
    db: Session = Depends(get_db),
    merchant: Merchant = Depends(get_current_merchant),
) -> ValidationResponse:
    """Run deterministic validation rules against the current case data."""
    case = db.get(RecoveryCase, case_id)
    if case is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Recovery case not found")
    verify_merchant_ownership(case, merchant.id, "Recovery Case")

    transaction = db.get(Transaction, case.transaction_id)
    customer = db.get(Customer, case.customer_id) if case.customer_id else None

    # Retrieve last customer submission details from action history
    last_sub = db.scalar(
        select(Action)
        .where(Action.recovery_case_id == case.id, Action.action_type == "CUSTOMER_RESPONSE")
        .order_by(Action.id.desc())
    )
    submission_data = json.loads(last_sub.details or "{}") if last_sub else {}

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

    # Safe state transitions based on deterministic outcome
    if val_result["status"] == "PASS":
        case.status = "settlement_ready"
        case.stage = "settlement_ready"
        _audit(db, "recovery_case", str(case.id), "settlement_ready", "Case reached settlement readiness following passing validation.", merchant_id=merchant.id)
    elif val_result["status"] == "FAIL":
        case.status = "validation_failed"
        case.stage = "action_required"
        _audit(db, "recovery_case", str(case.id), "validation_failed", val_result["overall_reason"], merchant_id=merchant.id)
    else:  # REVIEW
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
def submit_merchant_review(
    case_id: int,
    payload: MerchantReviewRequest,
    db: Session = Depends(get_db),
    merchant: Merchant = Depends(get_current_merchant),
) -> MerchantReviewResponse:
    """Submit merchant review decision with authoritative validation gate."""
    case = db.get(RecoveryCase, case_id)
    if case is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Recovery case not found")
    verify_merchant_ownership(case, merchant.id, "Recovery Case")

    # Authoritative Validation Enforcement: Check if validation failed
    latest_val = db.scalar(
        select(ValidationResult)
        .where(ValidationResult.recovery_case_id == case.id)
        .order_by(ValidationResult.id.desc())
    )

    if latest_val and not latest_val.passed and payload.decision == "APPROVE":
        val_data = json.loads(latest_val.details or "{}")
        if val_data.get("status") == "FAIL":
            logger.warning(
                "Merchant %s attempted to approve Case #%s despite failed deterministic validation.",
                merchant.id,
                case.id,
            )
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot approve a case that failed deterministic validation checks. Reason: "
                + val_data.get("overall_reason", "Validation failed"),
            )

    if payload.decision not in {"APPROVE", "REJECT", "REQUEST_MORE_INFORMATION", "REQUEST_MORE_INFO"}:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid review decision '{payload.decision}'. Allowed: APPROVE, REJECT, REQUEST_MORE_INFORMATION",
        )

    # Apply Decision
    previous_status = case.status
    if payload.decision == "APPROVE":
        case.status = "recovered"
        case.stage = "recovered"
        case.recovery_probability = Decimal("1.00")
        case.next_best_action = "SETTLEMENT_UNBLOCKED"
        action_type = "MERCHANT_REVIEW_APPROVE"
        log_event = "merchant_approved"
    elif payload.decision == "REJECT":
        case.status = "closed"
        case.stage = "recovery_rejected"
        case.recovery_probability = Decimal("0.00")
        case.next_best_action = "CASE_CLOSED"
        action_type = "MERCHANT_REVIEW_REJECTED"
        log_event = "recovery_rejected"
    else:  # REQUEST_MORE_INFO
        case.status = "action_required"
        case.stage = "settlement_risk"
        case.next_best_action = "REQUEST_INFORMATION"
        action_type = "MERCHANT_REVIEW_MORE_INFO"
        log_event = "resolution_requested"

    # Persist Action
    db.add(
        Action(
            recovery_case_id=case.id,
            action_type=action_type,
            status="completed",
            details=f"Decision: {payload.decision}. Notes: {payload.notes or 'None'}",
            reason=payload.notes,
            confidence=Decimal("1.000"),
        )
    )

    _audit(
        db,
        "recovery_case",
        str(case.id),
        log_event,
        f"Merchant {merchant.id} submitted review: {payload.decision}. Previous status: {previous_status}. Notes: {payload.notes or 'None'}",
        merchant_id=merchant.id,
    )

    db.commit()
    db.refresh(case)

    return MerchantReviewResponse(
        case_id=case.id,
        decision=payload.decision,
        case_status=case.status,
        case_stage=case.stage,
        notes=payload.notes,
        reviewed_at=datetime.now(UTC),
    )


@router.get("/{case_id}/resolution", response_model=CaseResolutionDetails)
def get_case_resolution_details(
    case_id: int,
    db: Session = Depends(get_db),
    merchant: Merchant = Depends(get_current_merchant),
) -> CaseResolutionDetails:
    """Get complete resolution workflow details for a case."""
    case = db.get(RecoveryCase, case_id)
    if case is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Recovery case not found")
    verify_merchant_ownership(case, merchant.id, "Recovery Case")

    # Fetch last resolution request action
    req_action = db.scalar(
        select(Action)
        .where(Action.recovery_case_id == case.id, Action.action_type == "CUSTOMER_RESOLUTION_REQUESTED")
        .order_by(Action.id.desc())
    )
    req_data = json.loads(req_action.details or "{}") if req_action else {}

    # Fetch last customer response action
    resp_action = db.scalar(
        select(Action)
        .where(Action.recovery_case_id == case.id, Action.action_type == "CUSTOMER_RESPONSE")
        .order_by(Action.id.desc())
    )
    cust_submission = json.loads(resp_action.details or "{}") if resp_action else None

    # Fetch attached documents
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
            AuditLog.merchant_id == merchant.id,
            or_(
                (AuditLog.entity_id == str(case.id)),
                (AuditLog.entity_id == str(case.transaction_id)),
            ),
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
    """Return recovery orchestration cases strictly scoped to current merchant."""
    cases = db.scalars(
        select(RecoveryCase)
        .where(RecoveryCase.merchant_id == merchant.id)
        .order_by(RecoveryCase.created_at.desc())
    ).all()
    logger.info("Listed %s recovery cases for merchant %s", len(cases), merchant.id)
    return cases
