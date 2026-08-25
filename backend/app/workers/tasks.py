from __future__ import annotations

import json
import logging
from typing import Any

from sqlalchemy import select

from app.database.session import SessionLocal
from app.models.audit_log import AuditLog
from app.models.customer import Customer
from app.models.transaction import Transaction
from app.models.webhook_event import WebhookEvent
from app.services.razorpay_service import RazorpayService
from app.services.recovery_service import analyze_transaction

logger = logging.getLogger(__name__)

STATUS_PRECEDENCE = {
    "created": 1,
    "authorized": 2,
    "payment_verified": 3,
    "captured": 4,
    "action_required": 5,
    "settlement_ready": 6,
    "recovered": 7,
    "failed": 0,
    "refunded": 8,
}


def _audit(db: Any, entity_id: str, event_type: str, details: str, merchant_id: int = 1) -> None:
    db.add(
        AuditLog(
            merchant_id=merchant_id,
            entity_type="webhook_event",
            entity_id=entity_id,
            event_type=event_type,
            details=details,
        )
    )


def process_razorpay_webhook(event_id: str) -> None:
    """Normalize one persisted event with state-machine precedence and multi-tenant security."""
    db = SessionLocal()
    try:
        webhook_event = db.scalar(select(WebhookEvent).where(WebhookEvent.event_id == event_id))
        if webhook_event is None or webhook_event.status == "processed":
            return
        webhook_event.status = "processing"
        db.commit()

        payload = json.loads(webhook_event.payload or "{}")
        service = RazorpayService()
        payment = service.payment_entity(payload)
        if not webhook_event.event_type.startswith("payment.") or payment is None:
            webhook_event.status = "ignored"
            _audit(db, event_id, "webhook_ignored", "Unsupported event type or no payment entity.")
            db.commit()
            return

        payment_id = payment.get("id")
        if not payment_id:
            raise ValueError("Payment event did not include a payment ID")

        order_id = str(payment["order_id"]) if payment.get("order_id") else None
        currency = str(payment.get("currency") or "INR").upper()

        transaction = db.scalar(select(Transaction).where(Transaction.external_id == str(payment_id)))
        if transaction is None and order_id:
            transaction = db.scalar(select(Transaction).where(Transaction.order_id == str(order_id)))

        incoming_status = str(payment.get("status") or "captured")

        if transaction is None:
            transaction = Transaction(
                merchant_id=1,
                external_id=str(payment_id),
                order_id=order_id,
                amount=service.normalize_amount(payment.get("amount"), currency),
                currency=currency,
                status=incoming_status,
            )
            db.add(transaction)
        else:
            transaction.external_id = str(payment_id)
            if order_id:
                transaction.order_id = str(order_id)
            transaction.amount = service.normalize_amount(payment.get("amount"), currency)
            transaction.currency = currency

            # Out-of-order event resilience: Do not regress higher precedence status
            curr_rank = STATUS_PRECEDENCE.get(transaction.status, 0)
            in_rank = STATUS_PRECEDENCE.get(incoming_status, 0)
            if in_rank >= curr_rank or transaction.status in {"pending", "created"}:
                transaction.status = incoming_status
            else:
                logger.info(
                    "Preserved higher status '%s' over out-of-order incoming status '%s' for transaction %s",
                    transaction.status,
                    incoming_status,
                    transaction.id,
                )

        customer_id = payment.get("customer_id")
        if customer_id:
            customer = db.scalar(select(Customer).where(Customer.external_id == str(customer_id)))
            if customer is None:
                customer = Customer(external_id=str(customer_id))
                db.add(customer)
                db.flush()
            transaction.customer_id = customer.id

        transaction.payment_method = str(payment["method"]) if payment.get("method") else None
        transaction.event_type = webhook_event.event_type
        transaction.country_code = str(payment["country_code"]) if payment.get("country_code") else (transaction.country_code or "IN")
        created_at = service.payment_timestamp(payment.get("created_at"))
        if created_at is not None:
            transaction.created_at = created_at

        webhook_event.status = "processed"
        _audit(db, event_id, "webhook_processed", f"Payment {payment_id} normalized.")
        db.commit()
        analyze_transaction(transaction.id, db)
        logger.info("Processed Razorpay webhook event %s", event_id)
    except Exception:
        db.rollback()
        try:
            webhook_event = db.scalar(select(WebhookEvent).where(WebhookEvent.event_id == event_id))
            if webhook_event is not None:
                webhook_event.status = "failed"
                _audit(db, event_id, "webhook_failed", "Worker processing failed; see server logs.")
                db.commit()
        except Exception:
            db.rollback()
        logger.exception("Razorpay webhook worker failed for event %s", event_id)
        raise
    finally:
        db.close()
