from __future__ import annotations

import json
import logging

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.dependencies import get_current_merchant
from app.database.session import get_db
from app.models.audit_log import AuditLog
from app.models.merchant import Merchant
from app.models.recovery_case import RecoveryCase
from app.models.webhook_event import WebhookEvent
from app.services.razorpay_service import RazorpayService
from app.services.webhook_recovery_service import WebhookRecoveryService
from app.workers.durable_queue import webhook_queue
from app.workers.tasks import process_razorpay_webhook

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/webhooks", tags=["webhooks"])


def _audit(db: Session, event_id: str, event_type: str, details: str, merchant_id: int = 1) -> None:
    db.add(
        AuditLog(
            merchant_id=merchant_id,
            entity_type="webhook_event",
            entity_id=event_id,
            event_type=event_type,
            details=details,
        )
    )


async def _accept_razorpay_webhook(
    body: bytes,
    signature: str | None,
    supplied_event_id: str | None,
    background_tasks: BackgroundTasks,
    db: Session,
) -> dict[str, str | bool]:
    service = RazorpayService()
    service.validate_test_mode_configuration()
    if not service.verify_webhook_signature(body, signature):
        logger.warning("Rejected Razorpay webhook with invalid signature")
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid webhook signature")

    try:
        payload = service.parse_payload(body)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    # Replay protection check
    if not service.verify_webhook_replay_protection(payload):
        logger.warning("Rejected replayed Razorpay webhook event")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Webhook event timestamp expired or replayed.",
        )

    event_id = service.event_id(payload, supplied_event_id, body)
    event_type = service.event_type(payload)
    existing = db.scalar(select(WebhookEvent).where(WebhookEvent.event_id == event_id))
    if existing is not None:
        _audit(db, event_id, "webhook_duplicate", f"Duplicate {event_type} event received.")
        db.commit()
        return {"status": "accepted", "duplicate": True, "event_id": event_id}

    webhook_event = WebhookEvent(
        event_id=event_id,
        event_type=event_type,
        payload=json.dumps(service.sanitize_payload(payload), separators=(",", ":")),
        status="received",
    )
    db.add(webhook_event)
    _audit(db, event_id, "webhook_received", f"Received {event_type} event.")
    try:
        db.commit()
    except IntegrityError:
        # Concurrent duplicate delivery
        db.rollback()
        return {"status": "accepted", "duplicate": True, "event_id": event_id}

    background_tasks.add_task(process_razorpay_webhook, event_id)
    return {"status": "accepted", "duplicate": False, "event_id": event_id}


@router.post("/razorpay", status_code=status.HTTP_200_OK)
async def razorpay_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
) -> dict[str, str | bool]:
    """Receive a signed Razorpay webhook and queue its asynchronous processing."""
    return await _accept_razorpay_webhook(
        body=await request.body(),
        signature=request.headers.get("X-Razorpay-Signature"),
        supplied_event_id=request.headers.get("X-Razorpay-Event-Id"),
        background_tasks=background_tasks,
        db=db,
    )


@router.post("/razorpay/test", status_code=status.HTTP_200_OK)
async def razorpay_webhook_test(
    request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
) -> dict[str, str | bool]:
    """Development-only helper that uses the normal signature-validation path."""
    if get_settings().environment.lower() not in {"development", "test"}:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    body = await request.body()
    service = RazorpayService()
    service.validate_test_mode_configuration()
    return await _accept_razorpay_webhook(
        body=body,
        signature=service.create_test_signature(body),
        supplied_event_id=request.headers.get("X-Razorpay-Event-Id"),
        background_tasks=background_tasks,
        db=db,
    )


# =========================================================================
# Webhook / Payment-State Recovery Endpoints
# =========================================================================
@router.post("/recovery/{transaction_id}/sync", status_code=status.HTTP_200_OK)
def resync_transaction_payment_state(
    transaction_id: int,
    current_merchant: Merchant = Depends(get_current_merchant),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Deterministically synchronize transaction payment state with authoritative Razorpay API."""
    recovery_service = WebhookRecoveryService()
    return recovery_service.resync_payment_state(
        transaction_id=transaction_id,
        merchant_id=current_merchant.id,
        db=db,
    )


@router.post("/recovery/detect", status_code=status.HTTP_200_OK)
def trigger_unresolved_mismatch_detection(
    current_merchant: Merchant = Depends(get_current_merchant),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Scan and detect payment-state mismatches for unresolved transactions."""
    recovery_service = WebhookRecoveryService()
    detected_cases = recovery_service.scan_and_detect_unresolved(
        merchant_id=current_merchant.id,
        db=db,
    )
    return {
        "status": "scan_completed",
        "merchant_id": current_merchant.id,
        "cases_detected_count": len(detected_cases),
        "case_ids": [c.id for c in detected_cases],
    }


@router.get("/recovery/mismatches", status_code=status.HTTP_200_OK)
def list_webhook_payment_state_exceptions(
    current_merchant: Merchant = Depends(get_current_merchant),
    db: Session = Depends(get_db),
) -> list[dict[str, Any]]:
    """List open webhook / payment-state exception recovery cases for the authenticated merchant."""
    cases = list(
        db.scalars(
            select(RecoveryCase)
            .where(
                RecoveryCase.merchant_id == current_merchant.id,
                RecoveryCase.exception_type == "webhook_payment_state_exception",
            )
            .order_by(RecoveryCase.id.desc())
        ).all()
    )

    results = []
    for c in cases:
        results.append({
            "case_id": c.id,
            "transaction_id": c.transaction_id,
            "customer_id": c.customer_id,
            "status": c.status,
            "stage": c.stage,
            "amount_at_risk": str(c.amount_at_risk) if c.amount_at_risk is not None else "0.00",
            "priority": c.priority,
            "next_best_action": c.next_best_action,
            "created_at": c.created_at.isoformat() if c.created_at else None,
            "updated_at": c.updated_at.isoformat() if c.updated_at else None,
        })
    return results
