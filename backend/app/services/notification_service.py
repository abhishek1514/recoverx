"""In-app mock notification service for customer recovery resolutions."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from app.models.customer import Customer
from app.models.recovery_case import RecoveryCase
from app.models.transaction import Transaction


class NotificationService:
    """Mock in-app notification dispatcher for RecoverX MVP."""

    @staticmethod
    def create_resolution_notification(
        case: RecoveryCase,
        transaction: Transaction,
        customer: Customer | None,
        missing_information: list[str],
        next_best_action: str,
    ) -> dict[str, Any]:
        """Generate structured in-app resolution request notification."""
        recipient = customer.email if (customer and customer.email) else f"customer_{case.customer_id or 'unknown'}"
        requested_info: list[str] = []
        requested_document_type: str | None = None

        if "customer_information" in missing_information or next_best_action == "REQUEST_INFORMATION":
            requested_info.extend(["name", "email", "country_code"])

        if "invoice_or_document" in missing_information or next_best_action == "REQUEST_DOCUMENT":
            requested_info.extend(["invoice_amount", "invoice_currency", "invoice_reference"])
            requested_document_type = "invoice"

        if not requested_info:
            requested_info = ["invoice_amount", "invoice_currency", "invoice_reference"]
            requested_document_type = "invoice"

        # Build clean customer-facing message
        amount_str = f"{transaction.amount} {transaction.currency}"
        if requested_document_type:
            msg = (
                f"We are processing your payment of {amount_str} (Ref: {transaction.external_id or 'N/A'}). "
                f"To finalize settlement readiness and protect your transaction, please upload your matching "
                f"commercial invoice or supporting documentation along with your invoice reference number."
            )
        else:
            msg = (
                f"We are reviewing your transaction of {amount_str} (Ref: {transaction.external_id or 'N/A'}). "
                f"Please confirm your account profile information (full legal name, email, and country code) "
                f"to complete the verification."
            )

        return {
            "case_id": case.id,
            "recipient": recipient,
            "subject": f"Action Required: Information requested for payment {transaction.external_id or case.id}",
            "requested_information": sorted(list(set(requested_info))),
            "requested_document_type": requested_document_type,
            "customer_message": msg,
            "status": "delivered",
            "created_at": datetime.now(UTC),
        }
