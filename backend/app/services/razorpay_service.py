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

    def _get_auth_tuple(self) -> tuple[str, str]:
        self.validate_test_mode_configuration()
        return (self.settings.razorpay_key_id.strip(), self.settings.razorpay_key_secret.strip())

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

        payload = {
            "amount": amount_subunits,
            "currency": currency_upper,
            "receipt": receipt_id,
            "notes": notes or {"created_by": "RecoverX Platform"},
        }

        try:
            with httpx.Client(timeout=10.0) as client:
                response = client.post(
                    "https://api.razorpay.com/v1/orders",
                    auth=(key_id, key_secret),
                    json=payload,
                )
                if response.status_code == 401:
                    logger.error("Razorpay API order creation failed (HTTP 401): Authentication failed")
                    raise HTTPException(
                        status_code=status.HTTP_401_UNAUTHORIZED,
                        detail="Authentication failed. Verify RAZORPAY_KEY_ID and RAZORPAY_KEY_SECRET.",
                    )
                if response.status_code != 200 and response.status_code != 201:
                    logger.error(
                        "Razorpay API order creation failed (HTTP %s): %s",
                        response.status_code,
                        response.text,
                    )
                    error_data = response.json() if response.headers.get("content-type", "").startswith("application/json") else {}
                    error_desc = error_data.get("error", {}).get("description", "Razorpay order creation failed.")
                    raise HTTPException(
                        status_code=status.HTTP_502_BAD_GATEWAY,
                        detail=f"Razorpay Orders API error: {error_desc}",
                    )

                order_data = response.json()
                logger.info("Created Razorpay order %s", order_data.get("id"))
                return {
                    "order_id": order_data.get("id"),
                    "amount": str(amount),
                    "currency": currency_upper,
                    "key_id": key_id,
                    "amount_subunits": amount_subunits,
                    "receipt": receipt_id,
                    "status": order_data.get("status", "created"),
                    "raw_order": order_data,
                }
        except httpx.RequestError as exc:
            logger.error("Network error communicating with Razorpay Orders API: %s", exc)
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Could not reach Razorpay Orders API. Check network connectivity.",
            ) from exc

    # =========================================================================
    # Razorpay Payment & Order Fetch API Client
    # =========================================================================
    def fetch_payment(self, payment_id: str) -> dict[str, Any]:
        """Fetch authoritative payment entity via official Razorpay Payments API (GET /v1/payments/{id})."""
        auth = self._get_auth_tuple()
        clean_id = payment_id.strip()
        try:
            with httpx.Client(timeout=10.0) as client:
                response = client.get(f"https://api.razorpay.com/v1/payments/{clean_id}", auth=auth)
                if response.status_code == 404:
                    raise HTTPException(
                        status_code=status.HTTP_404_NOT_FOUND,
                        detail=f"Payment {clean_id} not found on Razorpay.",
                    )
                if response.status_code != 200:
                    logger.error("Razorpay fetch_payment failed (HTTP %s): %s", response.status_code, response.text)
                    raise HTTPException(
                        status_code=status.HTTP_502_BAD_GATEWAY,
                        detail=f"Razorpay API error fetching payment {clean_id}.",
                    )
                return response.json()
        except httpx.RequestError as exc:
            logger.error("Network error fetching payment from Razorpay: %s", exc)
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Could not reach Razorpay Payments API.",
            ) from exc

    def fetch_order(self, order_id: str) -> dict[str, Any]:
        """Fetch authoritative order entity via official Razorpay Orders API (GET /v1/orders/{id})."""
        auth = self._get_auth_tuple()
        clean_id = order_id.strip()
        try:
            with httpx.Client(timeout=10.0) as client:
                response = client.get(f"https://api.razorpay.com/v1/orders/{clean_id}", auth=auth)
                if response.status_code == 404:
                    raise HTTPException(
                        status_code=status.HTTP_404_NOT_FOUND,
                        detail=f"Order {clean_id} not found on Razorpay.",
                    )
                if response.status_code != 200:
                    logger.error("Razorpay fetch_order failed (HTTP %s): %s", response.status_code, response.text)
                    raise HTTPException(
                        status_code=status.HTTP_502_BAD_GATEWAY,
                        detail=f"Razorpay API error fetching order {clean_id}.",
                    )
                return response.json()
        except httpx.RequestError as exc:
            logger.error("Network error fetching order from Razorpay: %s", exc)
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Could not reach Razorpay Orders API.",
            ) from exc

    # =========================================================================
    # Razorpay Dispute API Client
    # =========================================================================
    def get_dispute(self, dispute_id: str) -> dict[str, Any]:
        """Fetch dispute details via official Razorpay Disputes API (GET /v1/disputes/{id})."""
        auth = self._get_auth_tuple()
        clean_id = dispute_id.strip()
        try:
            with httpx.Client(timeout=10.0) as client:
                response = client.get(f"https://api.razorpay.com/v1/disputes/{clean_id}", auth=auth)
                if response.status_code == 404:
                    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Dispute {clean_id} not found on Razorpay.")
                if response.status_code != 200:
                    logger.error("Razorpay get_dispute failed (HTTP %s): %s", response.status_code, response.text)
                    raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=f"Razorpay API error fetching dispute {clean_id}.")
                return response.json()
        except httpx.RequestError as exc:
            logger.error("Network error fetching dispute from Razorpay: %s", exc)
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Could not reach Razorpay Disputes API.") from exc

    def contest_dispute(
        self,
        dispute_id: str,
        summary: str,
        documents: list[str] | None = None,
        amount: int | None = None,
        action: str = "submit",
    ) -> dict[str, Any]:
        """Submit contest evidence via official Razorpay Disputes API (PATCH /v1/disputes/{id}/contest)."""
        auth = self._get_auth_tuple()
        clean_id = dispute_id.strip()
        payload: dict[str, Any] = {
            "summary": summary,
            "action": action,
            "documents": documents or [],
        }
        if amount is not None:
            payload["amount"] = amount

        try:
            with httpx.Client(timeout=15.0) as client:
                response = client.patch(f"https://api.razorpay.com/v1/disputes/{clean_id}/contest", auth=auth, json=payload)
                if response.status_code != 200 and response.status_code != 201:
                    logger.error("Razorpay contest_dispute failed (HTTP %s): %s", response.status_code, response.text)
                    error_data = response.json() if response.headers.get("content-type", "").startswith("application/json") else {}
                    error_desc = error_data.get("error", {}).get("description", "Contest submission failed.")
                    raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=f"Razorpay Contest API error: {error_desc}")
                return response.json()
        except httpx.RequestError as exc:
            logger.error("Network error contesting dispute on Razorpay: %s", exc)
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Could not reach Razorpay Contest API.") from exc

    # =========================================================================
    # Razorpay Settlement API Client
    # =========================================================================
    def get_settlements(
        self,
        from_timestamp: int | None = None,
        to_timestamp: int | None = None,
        count: int = 10,
        skip: int = 0,
    ) -> list[dict[str, Any]]:
        """List settlements via official Razorpay Settlements API (GET /v1/settlements)."""
        auth = self._get_auth_tuple()
        params: dict[str, Any] = {"count": count, "skip": skip}
        if from_timestamp is not None:
            params["from"] = from_timestamp
        if to_timestamp is not None:
            params["to"] = to_timestamp

        try:
            with httpx.Client(timeout=10.0) as client:
                response = client.get("https://api.razorpay.com/v1/settlements", auth=auth, params=params)
                if response.status_code != 200:
                    logger.error("Razorpay get_settlements failed (HTTP %s): %s", response.status_code, response.text)
                    raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Razorpay Settlements API error.")
                data = response.json()
                return data.get("items", []) if isinstance(data, dict) else []
        except httpx.RequestError as exc:
            logger.error("Network error fetching settlements from Razorpay: %s", exc)
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Could not reach Razorpay Settlements API.") from exc

    def get_settlement_by_id(self, settlement_id: str) -> dict[str, Any]:
        """Fetch settlement details via official Razorpay Settlements API (GET /v1/settlements/{id})."""
        auth = self._get_auth_tuple()
        clean_id = settlement_id.strip()
        try:
            with httpx.Client(timeout=10.0) as client:
                response = client.get(f"https://api.razorpay.com/v1/settlements/{clean_id}", auth=auth)
                if response.status_code == 404:
                    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Settlement {clean_id} not found on Razorpay.")
                if response.status_code != 200:
                    logger.error("Razorpay get_settlement_by_id failed (HTTP %s): %s", response.status_code, response.text)
                    raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=f"Razorpay Settlements API error for {clean_id}.")
                return response.json()
        except httpx.RequestError as exc:
            logger.error("Network error fetching settlement from Razorpay: %s", exc)
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Could not reach Razorpay Settlements API.") from exc

    def get_combined_recon_settlements(self, year: int, month: int, day: int) -> dict[str, Any]:
        """Fetch combined reconciliation file via official Razorpay Recon API (GET /v1/settlements/recon/combined)."""
        auth = self._get_auth_tuple()
        params = {"year": year, "month": month, "day": day}
        try:
            with httpx.Client(timeout=15.0) as client:
                response = client.get("https://api.razorpay.com/v1/settlements/recon/combined", auth=auth, params=params)
                if response.status_code != 200:
                    logger.error("Razorpay recon API failed (HTTP %s): %s", response.status_code, response.text)
                    raise HTTPException(
                        status_code=status.HTTP_502_BAD_GATEWAY,
                        detail="Razorpay Settlement Recon API error or feature not enabled for this account.",
                    )
                return response.json()
        except httpx.RequestError as exc:
            logger.error("Network error fetching reconciliation from Razorpay: %s", exc)
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Could not reach Razorpay Recon API.") from exc

    # =========================================================================
    # Webhook Verification & Cryptographic Utilities
    # =========================================================================
    def verify_payment_signature(
        self,
        razorpay_order_id: str,
        razorpay_payment_id: str,
        razorpay_signature: str,
    ) -> bool:
        """Verify the payment signature returned by Razorpay Standard Checkout modal."""
        if not self.settings.razorpay_key_secret:
            return False
        message = f"{razorpay_order_id}|{razorpay_payment_id}"
        expected = hmac.new(
            self.settings.razorpay_key_secret.encode("utf-8"),
            message.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        return constant_time_compare(expected, razorpay_signature)

    def create_test_payment_signature(self, razorpay_order_id: str, razorpay_payment_id: str) -> str:
        """Used by test suites to generate valid payment signatures."""
        message = f"{razorpay_order_id}|{razorpay_payment_id}"
        return hmac.new(
            self.settings.razorpay_key_secret.encode("utf-8"),
            message.encode("utf-8"),
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

        tolerance = tolerance_seconds if tolerance_seconds is not None else int(getattr(self.settings, "webhook_tolerance_seconds", getattr(self.settings, "webhook_timestamp_tolerance_seconds", 300)))
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
