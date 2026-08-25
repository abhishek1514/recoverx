import logging
from decimal import Decimal

from fastapi import APIRouter, Depends
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.dependencies import get_current_merchant
from app.database.session import get_db
from app.models.merchant import Merchant
from app.models.recovery_case import RecoveryCase
from app.models.risk_assessment import RiskAssessment
from app.models.transaction import Transaction
from app.schemas.recovery import DashboardSummary

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


@router.get("/summary", response_model=DashboardSummary)
def get_dashboard_summary(
    db: Session = Depends(get_db),
    merchant: Merchant = Depends(get_current_merchant),
) -> DashboardSummary:
    """Return dashboard summary metrics scoped to the authenticated merchant."""
    merchant_filter = or_(Transaction.merchant_id == merchant.id, Transaction.merchant_id.is_(None))
    case_merchant_filter = or_(RecoveryCase.merchant_id == merchant.id, RecoveryCase.merchant_id.is_(None))

    total_transactions = db.scalar(
        select(func.count()).select_from(Transaction).where(merchant_filter)
    ) or 0

    high_value_transactions = db.scalar(
        select(func.count())
        .select_from(Transaction)
        .where(merchant_filter, Transaction.amount >= get_settings().get_high_value_threshold("INR"))
    ) or 0

    latest_assessment_ids = select(func.max(RiskAssessment.id)).group_by(RiskAssessment.transaction_id)
    latest_assessments = db.scalars(
        select(RiskAssessment)
        .join(Transaction, RiskAssessment.transaction_id == Transaction.id)
        .where(merchant_filter, RiskAssessment.id.in_(latest_assessment_ids))
    ).all()

    at_risk_transactions = sum(
        assessment.readiness_status in {"AT_RISK", "HIGH_RISK"} for assessment in latest_assessments
    )
    total_revenue_at_risk = sum(
        (Decimal(assessment.revenue_at_risk or 0) for assessment in latest_assessments), Decimal("0")
    )
    high_priority_cases = db.scalar(
        select(func.count())
        .select_from(RecoveryCase)
        .where(case_merchant_filter, RecoveryCase.priority == "HIGH")
    ) or 0
    probabilities = [
        Decimal(assessment.recovery_probability)
        for assessment in latest_assessments
        if assessment.recovery_probability is not None
    ]
    average_recovery_probability = (
        (sum(probabilities, Decimal("0")) / len(probabilities)).quantize(Decimal("0.001"))
        if probabilities
        else Decimal("0")
    )

    recovered_cases = db.scalars(
        select(RecoveryCase).where(case_merchant_filter, RecoveryCase.status == "recovered")
    ).all()
    recovered_revenue = sum((Decimal(c.amount_at_risk or 0) for c in recovered_cases), Decimal("0.00"))
    recovery_rate = (
        (recovered_revenue / total_revenue_at_risk).quantize(Decimal("0.001"))
        if total_revenue_at_risk > Decimal("0")
        else Decimal("0.00")
    )

    cases_awaiting_customer = db.scalar(
        select(func.count())
        .select_from(RecoveryCase)
        .where(case_merchant_filter, RecoveryCase.status == "action_required")
    ) or 0
    cases_awaiting_merchant_review = db.scalar(
        select(func.count())
        .select_from(RecoveryCase)
        .where(case_merchant_filter, RecoveryCase.status == "merchant_review")
    ) or 0
    settlement_ready_cases = db.scalar(
        select(func.count())
        .select_from(RecoveryCase)
        .where(case_merchant_filter, RecoveryCase.status == "settlement_ready")
    ) or 0

    summary = DashboardSummary(
        total_transactions=total_transactions,
        high_value_transactions=high_value_transactions,
        at_risk_transactions=at_risk_transactions,
        total_revenue_at_risk=total_revenue_at_risk,
        high_priority_cases=high_priority_cases,
        average_recovery_probability=average_recovery_probability,
        recovered_revenue=recovered_revenue,
        recovery_rate=recovery_rate,
        cases_awaiting_customer=cases_awaiting_customer,
        cases_awaiting_merchant_review=cases_awaiting_merchant_review,
        settlement_ready_cases=settlement_ready_cases,
    )
    logger.info("Returned dashboard summary for merchant %s", merchant.id)
    return summary
