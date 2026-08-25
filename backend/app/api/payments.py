import logging
from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.currencies import check_country_currency_alignment
from app.core.dependencies import get_current_merchant, verify_merchant_ownership
from app.database.session import get_db
from app.models.audit_log import AuditLog
from app.models.customer import Customer
from app.models.document import Document
from app.models.merchant import Merchant
from app.models.recovery_case import RecoveryCase
from app.models.risk_assessment import RiskAssessment
from app.models.transaction import Transaction
from app.schemas.payment import (
    RazorpayOrderCreate,
    RazorpayOrderResponse,
    RazorpayOrderStatusResponse,
    RazorpayPaymentVerifyRequest,
    RazorpayPaymentVerifyResponse,
    TestTransactionCreate,
    TestTransactionResponse,
    TimelineEvent,
    TransactionRead,
)
from app.services.razorpay_service import RazorpayService
from app.services.recovery_service import analyze_transaction

logger = logging.getLogger(__name__)

router = APIRouter(tags=["payments"])


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


# =====================================================================
# 1. Existing Transaction Endpoints
# =====================================================================

@router.get("/api/transactions", response_model=list[TransactionRead])
def list_transactions(
    db: Session = Depends(get_db),
    merchant: Merchant = Depends(get_current_merchant),
) -> list[Transaction]:
    """Return transaction records scoped to current merchant."""
    transactions = db.scalars(
        select(Transaction)
        .where(or_(Transaction.merchant_id == merchant.id, Transaction.merchant_id.is_(None)))
        .order_by(Transaction.created_at.desc())
    ).all()
    logger.info("Listed %s transaction records for merchant %s", len(transactions), merchant.id)
    return transactions


@router.post("/api/transactions/test", response_model=TestTransactionResponse, status_code=status.HTTP_201_CREATED)
def create_test_transaction(
    payload: TestTransactionCreate,
    db: Session = Depends(get_db),
    merchant: Merchant = Depends(get_current_merchant),
) -> TestTransactionResponse:
    """Create an interactive test transaction and execute the live RecoverX intelligence pipeline."""
    cust_id = f"cust_test_{uuid4().hex[:8]}"
    if payload.customer_information_complete:
        customer = Customer(
            external_id=cust_id,
            name=payload.customer_name or "Test Enterprise Customer",
            email=payload.customer_email or "billing@testenterprise.com",
            country_code=payload.country_code,
        )
    else:
        customer = Customer(
            external_id=cust_id,
            name=payload.customer_name or "",
            email=payload.customer_email or "",
            country_code=payload.country_code,
        )
    db.add(customer)
    db.flush()

    ext_id = f"pay_test_{uuid4().hex[:12]}"
    order_id = f"order_test_{uuid4().hex[:12]}"
    payment_method = "upi" if payload.currency == "INR" else "card"

    transaction = Transaction(
        merchant_id=merchant.id,
        external_id=ext_id,
        order_id=order_id,
        customer_id=customer.id,
        amount=payload.amount,
        currency=payload.currency,
        status=payload.payment_status,
        payment_method=payment_method,
        country_code=payload.country_code,
        event_type="test.transaction.created",
    )
    db.add(transaction)
    db.flush()

    if payload.document_available:
        recovery_case = RecoveryCase(
            merchant_id=merchant.id,
            transaction_id=transaction.id,
            customer_id=customer.id,
        )
        db.add(recovery_case)
        db.flush()
        doc = Document(
            merchant_id=merchant.id,
            recovery_case_id=recovery_case.id,
            document_type="invoice",
            reference=payload.invoice_reference or f"documents/test_{uuid4().hex[:8]}.pdf",
            status="available",
        )
        db.add(doc)
        db.commit()

    case = analyze_transaction(transaction.id, db)
    if case:
        case.merchant_id = merchant.id
        db.commit()

    assessment = db.scalar(
        select(RiskAssessment)
        .where(RiskAssessment.transaction_id == transaction.id)
        .order_by(RiskAssessment.id.desc())
    )

    settings = get_settings()
    is_high_val = payload.amount >= settings.get_high_value_threshold(payload.currency)

    logger.info(
        "Created test transaction %s (%s %s) for merchant %s -> Case #%s",
        transaction.id,
        transaction.amount,
        transaction.currency,
        merchant.id,
        case.id,
    )

    alignment = check_country_currency_alignment(transaction.country_code or "IN", transaction.currency)

    return TestTransactionResponse(
        transaction_id=transaction.id,
        amount=transaction.amount,
        currency=transaction.currency,
        country_code=transaction.country_code or "IN",
        is_high_value=is_high_val,
        risk_score=assessment.risk_score or assessment.settlement_risk_score or Decimal(0),
        readiness_status=assessment.readiness_status or case.stage,
        revenue_at_risk=case.amount_at_risk or Decimal(0),
        recovery_probability=case.recovery_probability or Decimal(0),
        next_best_action=case.next_best_action or "MERCHANT_REVIEW",
        case_id=case.id,
        is_cross_border_mismatch=bool(alignment["is_mismatch"]),
        currency_note=str(alignment["note"]),
    )


# =====================================================================
# 2. Razorpay Test Checkout Endpoints
# =====================================================================

@router.post("/api/payments/create-order", response_model=RazorpayOrderResponse, status_code=status.HTTP_201_CREATED)
def create_razorpay_order(
    payload: RazorpayOrderCreate,
    db: Session = Depends(get_db),
    merchant: Merchant = Depends(get_current_merchant),
) -> RazorpayOrderResponse:
    """Create a new Razorpay Test Order and persist the initial Transaction order record."""
    service = RazorpayService()
    service.validate_test_mode_configuration()

    order_result = service.create_order(
        amount=payload.amount,
        currency=payload.currency,
        receipt=payload.receipt,
    )

    customer_id = None
    if payload.customer_email or payload.customer_name:
        cust_ext_id = f"cust_rzp_{uuid4().hex[:8]}"
        customer = Customer(
            external_id=cust_ext_id,
            name=payload.customer_name or "Test Checkout Customer",
            email=payload.customer_email or "checkout@testrecoverx.io",
            country_code="IN" if payload.currency == "INR" else "US",
        )
        db.add(customer)
        db.flush()
        customer_id = customer.id

    transaction = Transaction(
        merchant_id=merchant.id,
        order_id=order_result["order_id"],
        external_id=None,
        customer_id=customer_id,
        amount=order_result["amount"],
        currency=order_result["currency"],
        status="created",
        payment_method="razorpay_checkout",
        country_code="IN" if payload.currency == "INR" else "US",
        event_type="order.created",
    )
    db.add(transaction)
    _audit(db, "order", order_result["order_id"], "order_created", f"Razorpay order created for {order_result['amount']} {order_result['currency']}", merchant_id=merchant.id)
    db.commit()

    logger.info("Persisted order %s with amount %s %s for merchant %s", order_result["order_id"], payload.amount, payload.currency, merchant.id)

    return RazorpayOrderResponse(
        order_id=order_result["order_id"],
        amount=order_result["amount"],
        currency=order_result["currency"],
        key_id=order_result["key_id"],
        amount_subunits=order_result["amount_subunits"],
        receipt=order_result.get("receipt"),
        status=order_result.get("status", "created"),
    )


@router.post("/api/payments/verify", response_model=RazorpayPaymentVerifyResponse, status_code=status.HTTP_200_OK)
def verify_razorpay_payment(
    payload: RazorpayPaymentVerifyRequest,
    db: Session = Depends(get_db),
    merchant: Merchant = Depends(get_current_merchant),
) -> RazorpayPaymentVerifyResponse:
    """Verify Razorpay payment signature against server-stored order records with timing-safe comparison."""
    service = RazorpayService()
    service.validate_test_mode_configuration()

    transaction = db.scalar(select(Transaction).where(Transaction.order_id == payload.razorpay_order_id))
    if transaction is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Order '{payload.razorpay_order_id}' was not found in server records.",
        )
    verify_merchant_ownership(transaction, merchant.id, "Transaction Order")

    is_valid = service.verify_payment_signature(
        razorpay_order_id=payload.razorpay_order_id,
        razorpay_payment_id=payload.razorpay_payment_id,
        razorpay_signature=payload.razorpay_signature,
    )
    if not is_valid:
        logger.warning("Invalid payment signature received for order %s", payload.razorpay_order_id)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid payment signature. Verification failed.",
        )

    transaction.external_id = payload.razorpay_payment_id
    transaction.status = "payment_verified"
    _audit(db, "payment", payload.razorpay_payment_id, "payment_verified", f"Signature verified for order {payload.razorpay_order_id}", merchant_id=merchant.id)
    db.commit()

    return RazorpayPaymentVerifyResponse(
        verified=True,
        payment_id=payload.razorpay_payment_id,
        order_id=payload.razorpay_order_id,
        status="payment_verified",
        message="Payment signature successfully verified.",
    )


@router.get("/api/payments/order/{order_id}/status", response_model=RazorpayOrderStatusResponse, status_code=status.HTTP_200_OK)
def get_order_status(
    order_id: str,
    db: Session = Depends(get_db),
    merchant: Merchant = Depends(get_current_merchant),
) -> RazorpayOrderStatusResponse:
    """Live status polling endpoint for frontend to monitor Webhook ingestion and RecoverX analysis."""
    transaction = db.scalar(select(Transaction).where(Transaction.order_id == order_id))
    if transaction is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Order '{order_id}' not found.",
        )
    verify_merchant_ownership(transaction, merchant.id, "Transaction Order")

    case = db.scalar(
        select(RecoveryCase)
        .where(RecoveryCase.transaction_id == transaction.id)
        .order_by(RecoveryCase.id.desc())
    )
    assessment = db.scalar(
        select(RiskAssessment)
        .where(RiskAssessment.transaction_id == transaction.id)
        .order_by(RiskAssessment.id.desc())
    )

    now = datetime.now(UTC)
    has_webhook = bool(transaction.event_type and transaction.event_type.startswith("payment.")) or transaction.status in {"captured", "settlement_ready", "recovered"}
    has_case = case is not None
    is_verified = transaction.status in {"payment_verified", "captured", "settlement_ready", "recovered"}

    timeline = [
        TimelineEvent(
            key="initiated",
            title="Payment Initiated",
            description=f"Order {order_id} created in Razorpay Test Mode.",
            status="completed",
            timestamp=transaction.created_at,
        ),
        TimelineEvent(
            key="checkout",
            title="Razorpay Test Checkout",
            description="User completed payment in Razorpay Checkout modal.",
            status="completed" if is_verified or transaction.external_id else "in_progress",
            timestamp=transaction.created_at,
        ),
        TimelineEvent(
            key="verified",
            title="Payment Signature Verified",
            description="HMAC SHA-256 signature verified server-side with secret.",
            status="completed" if is_verified else ("pending" if not transaction.external_id else "in_progress"),
            timestamp=now if is_verified else None,
        ),
        TimelineEvent(
            key="webhook",
            title="Razorpay Webhook Received",
            description="Server-to-server payment.captured webhook ingested and verified.",
            status="completed" if has_webhook else "pending",
            timestamp=now if has_webhook else None,
        ),
        TimelineEvent(
            key="analyzed",
            title="Settlement Risk Analysis",
            description="Deterministic intelligence computed settlement risk and revenue at risk.",
            status="completed" if has_case else "pending",
            timestamp=now if has_case else None,
        ),
        TimelineEvent(
            key="action",
            title="Recovery Action Identified",
            description=f"Action: {case.next_best_action if case else 'Pending intelligence engine'}",
            status="completed" if has_case and case.next_best_action else "pending",
            timestamp=now if has_case else None,
        ),
    ]

    return RazorpayOrderStatusResponse(
        order_id=transaction.order_id or order_id,
        payment_id=transaction.external_id,
        amount=transaction.amount,
        currency=transaction.currency,
        status=case.status if case else transaction.status,
        transaction_id=transaction.id,
        case_id=case.id if case else None,
        risk_score=assessment.risk_score if assessment else None,
        revenue_at_risk=case.amount_at_risk if case else None,
        recovery_probability=case.recovery_probability if case else None,
        next_best_action=case.next_best_action if case else None,
        timeline=timeline,
    )
