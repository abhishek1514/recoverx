from __future__ import annotations

import json
import logging

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.database.session import get_db
from app.models.audit_log import AuditLog
from app.models.webhook_event import WebhookEvent
from app.services.razorpay_service import RazorpayService
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
