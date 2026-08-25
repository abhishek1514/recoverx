"""Razorpay Test Mode service for order creation, signature verification, and event normalization.

This module enforces test-mode-only operations, timing-safe verification, and server-side secret handling.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import uuid4

import httpx
from fastapi import HTTPException, status

from app.core.config import Settings, get_settings
from app.core.security import constant_time_compare

logger = logging.getLogger(__name__)

SENSITIVE_KEYS = {"card", "card_id", "cvv", "token", "credential", "credentials", "password"}


class RazorpayService:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()

    def validate_test_mode_configuration(self) -> None:
        """Ensure only Razorpay Test Mode credentials are used. Reject live keys."""
        key_id = (self.settings.razorpay_key_id or "").strip()
        key_secret = (self.settings.razorpay_key_secret or "").strip()
        if not key_id or not key_secret:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Razorpay Test Mode credentials (RAZORPAY_KEY_ID and RAZORPAY_KEY_SECRET) are not configured.",
            )
        if not key_id.startswith("rzp_test_"):
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Only Razorpay Test Mode credentials (rzp_test_...) are permitted in this application.",
            )

    def create_order(
        self,
        amount: Decimal,
        currency: str = "INR",
        receipt: str | None = None,
        notes: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Create a real Razorpay Test Order via the official Razorpay Orders API."""
        self.validate_test_mode_configuration()

        if amount <= Decimal(0):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Payment amount must be strictly greater than 0.",
            )

        currency_upper = currency.upper().strip()
        exponent = 0 if currency_upper in {"JPY", "KRW"} else 2
        amount_subunits = int(amount * (Decimal(10) ** exponent))
        if amount_subunits <= 0:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Amount converts to zero currency subunits.",
            )

        receipt_id = receipt or f"recoverx_test_{uuid4().hex[:10]}"
        key_id = self.settings.razorpay_key_id.strip()
        key_secret = self.settings.razorpay_key_secret.strip()

        order_payload = {
            "amount": amount_subunits,
            "currency": currency_upper,
            "receipt": receipt_id,
            "notes": notes or {
                "source": "RecoverX",
                "environment": "test",
            },
        }

        try:
            with httpx.Client(auth=(key_id, key_secret), timeout=10.0) as client:
                resp = client.post(
                    "https://api.razorpay.com/v1/orders",
                    json=order_payload,
                )
        except Exception as exc:
            logger.error("Failed to connect to Razorpay Orders API: %s", exc)
            raise HTTPException(
                status_code=status.HTTP_504_GATEWAY_TIMEOUT,
                detail=f"Failed to connect to Razorpay Orders API: {str(exc)}",
            ) from exc

        if resp.status_code not in {200, 201}:
            try:
                err_data = resp.json()
                err_desc = (
                    err_data.get("error", {}).get("description")
                    or err_data.get("error", {}).get("code")
                    or resp.text
                )
            except Exception:
                err_desc = resp.text

            logger.error(
                "Razorpay API order creation failed (HTTP %s): %s",
                resp.status_code,
                err_desc,
            )
            status_code = (
                resp.status_code
                if resp.status_code in {400, 401, 403, 422}
                else status.HTTP_502_BAD_GATEWAY
            )
            raise HTTPException(
                status_code=status_code,
                detail=f"Razorpay order creation failed: {err_desc}",
            )

        order_data = resp.json()
        real_order_id = str(order_data["id"])
        logger.info("Created Razorpay order %s", real_order_id)

        return {
            "order_id": real_order_id,
            "amount": amount,
            "currency": currency_upper,
            "key_id": key_id,
            "amount_subunits": amount_subunits,
            "receipt": receipt_id,
            "status": str(order_data.get("status", "created")),
        }

    def verify_payment_signature(
        self,
        razorpay_order_id: str,
        razorpay_payment_id: str,
        razorpay_signature: str,
    ) -> bool:
        """Verify the payment signature returned by Razorpay Checkout with timing-safe comparison."""
        if not razorpay_signature or not self.settings.razorpay_key_secret:
            return False
        msg = f"{razorpay_order_id}|{razorpay_payment_id}".encode("utf-8")
        expected = hmac.new(
            self.settings.razorpay_key_secret.encode("utf-8"),
            msg,
            hashlib.sha256,
        ).hexdigest()
        return constant_time_compare(expected, razorpay_signature)

    def create_test_payment_signature(
        self,
        order_id: str,
        payment_id: str,
    ) -> str:
        """Generate a valid payment signature for automated unit tests."""
        msg = f"{order_id}|{payment_id}".encode("utf-8")
        return hmac.new(
            self.settings.razorpay_key_secret.encode("utf-8"),
            msg,
            hashlib.sha256,
        ).hexdigest()

    def verify_webhook_signature(self, body: bytes, signature: str | None) -> bool:
        """Verify the X-Razorpay-Signature header for webhook payloads using timing-safe comparison."""
        if not signature or not self.settings.razorpay_webhook_secret:
            return False
        expected = hmac.new(
            self.settings.razorpay_webhook_secret.encode("utf-8"), body, hashlib.sha256
        ).hexdigest()
        return constant_time_compare(expected, signature)

    def verify_webhook_replay_protection(
        self,
        payload: dict[str, Any],
        tolerance_seconds: int | None = None,
    ) -> bool:
        """Verify webhook timestamp against tolerance window to reject replay attacks."""
        if self.settings.environment.lower() == "test" and tolerance_seconds is None:
            return True

        tolerance = tolerance_seconds if tolerance_seconds is not None else self.settings.webhook_tolerance_seconds
        if tolerance <= 0:
            return True

        created_at_raw = payload.get("created_at")
        if not created_at_raw:
            payment = self.payment_entity(payload)
            if payment and payment.get("created_at"):
                created_at_raw = payment.get("created_at")

        if not created_at_raw:
            return True

        try:
            event_time = int(created_at_raw)
            current_time = int(datetime.now(UTC).timestamp())
            age = current_time - event_time
            if age > tolerance:
                logger.warning("Rejected replayed/stale webhook (age: %ss > tolerance: %ss)", age, tolerance)
                return False
            return True
        except (ValueError, TypeError):
            return True


    def create_test_signature(self, body: bytes) -> str:
        """Used only by development test routes and webhook unit tests."""
        return hmac.new(
            self.settings.razorpay_webhook_secret.encode("utf-8"), body, hashlib.sha256
        ).hexdigest()

    @staticmethod
    def parse_payload(body: bytes) -> dict[str, Any]:
        try:
            payload = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("Malformed JSON webhook payload") from exc
        if not isinstance(payload, dict):
            raise ValueError("Webhook payload must be a JSON object")
        return payload

    @staticmethod
    def event_id(payload: dict[str, Any], supplied_event_id: str | None, body: bytes) -> str:
        event_id = payload.get("event_id") or payload.get("id") or supplied_event_id
        return str(event_id) if event_id else f"payload_{hashlib.sha256(body).hexdigest()}"

    @staticmethod
    def event_type(payload: dict[str, Any]) -> str:
        return str(payload.get("event") or payload.get("event_type") or "unknown")

    @staticmethod
    def sanitize_payload(value: Any) -> Any:
        if isinstance(value, dict):
            return {
                key: RazorpayService.sanitize_payload(item)
                for key, item in value.items()
                if key.lower() not in SENSITIVE_KEYS
            }
        if isinstance(value, list):
            return [RazorpayService.sanitize_payload(item) for item in value]
        return value

    @staticmethod
    def payment_entity(payload: dict[str, Any]) -> dict[str, Any] | None:
        nested_payload = payload.get("payload")
        if isinstance(nested_payload, dict):
            payment = nested_payload.get("payment")
            if isinstance(payment, dict) and isinstance(payment.get("entity"), dict):
                return payment["entity"]
        payment = payload.get("payment")
        if isinstance(payment, dict):
            return payment.get("entity") if isinstance(payment.get("entity"), dict) else payment
        return None

    @staticmethod
    def normalize_amount(amount: Any, currency: str) -> Decimal:
        value = Decimal(str(amount or 0))
        exponent = 0 if currency.upper() in {"JPY", "KRW"} else 2
        return value / (Decimal(10) ** exponent)

    @staticmethod
    def payment_timestamp(created_at: Any) -> datetime | None:
        if created_at is None:
            return None
        try:
            return datetime.fromtimestamp(int(created_at), tz=UTC)
        except (TypeError, ValueError, OSError):
            return None
