"""Deterministic orchestration for RecoverX settlement-friction intelligence."""

from __future__ import annotations

import json
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.intelligence.next_best_action import select_next_best_action
from app.intelligence.recovery_probability import estimate_recovery_probability
from app.intelligence.revenue_at_risk import calculate_revenue_at_risk
from app.intelligence.settlement_readiness import analyze_settlement_readiness
from app.models.action import Action
from app.models.audit_log import AuditLog
from app.models.customer import Customer
from app.models.document import Document
from app.models.recovery_case import RecoveryCase
from app.models.risk_assessment import RiskAssessment
from app.models.transaction import Transaction


def _audit(db: Session, entity_type: str, entity_id: str, event_type: str, details: str) -> None:
    db.add(AuditLog(entity_type=entity_type, entity_id=entity_id, event_type=event_type, details=details))


def analyze_transaction(transaction_id: int, db: Session) -> RecoveryCase:
    """Run reproducible, explainable Phase 3 rules and persist their decisions."""
    transaction = db.get(Transaction, transaction_id)
    if transaction is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Transaction not found")

    customer = db.get(Customer, transaction.customer_id) if transaction.customer_id else None
    existing_case = db.scalar(select(RecoveryCase).where(RecoveryCase.transaction_id == transaction.id))
    has_document = bool(
        existing_case
        and db.scalar(
            select(Document.id).where(
                Document.recovery_case_id == existing_case.id, Document.status == "available"
            )
        )
    )
    previous_count = 0
    if customer is not None:
        previous_count = db.scalar(
            select(func.count()).select_from(Transaction).where(
                Transaction.customer_id == customer.id, Transaction.id != transaction.id
            )
        ) or 0

    readiness = analyze_settlement_readiness(transaction, customer, has_document, previous_count)
    revenue = calculate_revenue_at_risk(transaction.amount, readiness["risk_score"], readiness["is_high_value"])
    recovery = estimate_recovery_probability(transaction, customer, has_document, readiness)
    action_decision = select_next_best_action(readiness)

    assessment = RiskAssessment(
        transaction_id=transaction.id,
        settlement_risk_score=readiness["risk_score"], risk_score=readiness["risk_score"],
        readiness_status=readiness["readiness_status"],
        risk_reasons=json.dumps(readiness["risk_reasons"]),
        missing_information=json.dumps(readiness["missing_information"]),
        confidence=readiness["confidence"], revenue_at_risk=revenue["revenue_at_risk"],
        recovery_probability=recovery["recovery_probability"], status=readiness["readiness_status"],
        rationale="Deterministic Phase 3 settlement-readiness heuristic.",
    )
    db.add(assessment)

    recovery_case = existing_case or RecoveryCase(transaction_id=transaction.id, customer_id=transaction.customer_id)
    recovery_case.status = "settlement_ready" if readiness["readiness_status"] == "READY" else "open"
    recovery_case.stage = readiness["readiness_status"].lower()
    recovery_case.amount_at_risk = revenue["revenue_at_risk"]
    recovery_case.recovery_probability = recovery["recovery_probability"]
    recovery_case.priority = revenue["priority"]
    recovery_case.next_best_action = action_decision["action"]
    if existing_case is None:
        db.add(recovery_case)
        db.flush()

    db.add(Action(
        recovery_case_id=recovery_case.id, action_type=action_decision["action"],
        status="recommended", details=action_decision["reason"], reason=action_decision["reason"],
        confidence=action_decision["confidence"],
    ))
    _audit(db, "transaction", str(transaction.id), "settlement_readiness_analyzed", readiness["readiness_status"])
    _audit(db, "recovery_case", str(recovery_case.id), "recovery_action_recommended", action_decision["action"])
    db.commit()
    db.refresh(recovery_case)
    return recovery_case
