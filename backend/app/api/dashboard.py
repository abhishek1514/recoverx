import logging
from decimal import Decimal

from fastapi import APIRouter, Depends
from sqlalchemy import case, func, or_, select
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
    """Return dashboard summary metrics scoped to the authenticated merchant with consolidated SQL queries."""
    merchant_filter = or_(Transaction.merchant_id == merchant.id, Transaction.merchant_id.is_(None))
    case_merchant_filter = or_(RecoveryCase.merchant_id == merchant.id, RecoveryCase.merchant_id.is_(None))
    high_value_threshold = get_settings().get_high_value_threshold("INR")

    # 1. Consolidated Transaction Metrics (1 single aggregation query)
    tx_row = db.execute(
        select(
            func.count(Transaction.id).label("total_transactions"),
            func.count(Transaction.id).filter(Transaction.amount >= high_value_threshold).label("high_value_transactions"),
        ).where(merchant_filter)
    ).one()

    total_transactions = tx_row.total_transactions or 0
    high_value_transactions = tx_row.high_value_transactions or 0

    # 2. Consolidated Recovery Case Metrics (1 single aggregation query)
    case_row = db.execute(
        select(
            func.count(RecoveryCase.id).filter(RecoveryCase.priority == "HIGH").label("high_priority_cases"),
            func.count(RecoveryCase.id).filter(RecoveryCase.status == "action_required").label("cases_awaiting_customer"),
            func.count(RecoveryCase.id).filter(RecoveryCase.status == "merchant_review").label("cases_awaiting_merchant_review"),
            func.count(RecoveryCase.id).filter(RecoveryCase.status == "settlement_ready").label("settlement_ready_cases"),
            func.coalesce(
                func.sum(
                    case((RecoveryCase.status == "recovered", RecoveryCase.amount_at_risk), else_=Decimal("0.00"))
                ),
                Decimal("0.00"),
            ).label("recovered_revenue"),
        ).where(case_merchant_filter)
    ).one()

    high_priority_cases = case_row.high_priority_cases or 0
    cases_awaiting_customer = case_row.cases_awaiting_customer or 0
    cases_awaiting_merchant_review = case_row.cases_awaiting_merchant_review or 0
    settlement_ready_cases = case_row.settlement_ready_cases or 0
    recovered_revenue = Decimal(str(case_row.recovered_revenue or "0.00"))

    # 3. Latest Assessment Aggregations
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
        (Decimal(str(assessment.revenue_at_risk or 0)) for assessment in latest_assessments), Decimal("0")
    )

    probabilities = [
        Decimal(str(assessment.recovery_probability))
        for assessment in latest_assessments
        if assessment.recovery_probability is not None
    ]
    average_recovery_probability = (
        (sum(probabilities, Decimal("0")) / len(probabilities)).quantize(Decimal("0.001"))
        if probabilities
        else Decimal("0")
    )

    recovery_rate = (
        (recovered_revenue / total_revenue_at_risk).quantize(Decimal("0.001"))
        if total_revenue_at_risk > Decimal("0")
        else Decimal("0.00")
    )

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
