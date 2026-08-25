"""Deterministic validation engine for RecoverX revenue recovery."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.customer import Customer
from app.models.recovery_case import RecoveryCase
from app.models.transaction import Transaction
from app.models.validation import ValidationResult
from app.validation.document_validation import validate_case_documents


def validate_recovery_submission(
    case: RecoveryCase,
    transaction: Transaction,
    customer: Customer | None,
    submission_data: dict[str, Any],
    db: Session,
) -> dict[str, Any]:
    """Execute authoritative deterministic validation rules.
    
    Returns structured results with status PASS, FAIL, or REVIEW.
    """
    checks: list[dict[str, str]] = []
    has_critical_failure = False
    has_ambiguity_or_review = False

    # 1. Invoice Reference Check (Rule C)
    invoice_ref = (submission_data.get("invoice_reference") or submission_data.get("invoice_id") or "").strip()
    if not invoice_ref:
        checks.append({
            "name": "invoice_reference_check",
            "status": "FAIL",
            "message": "Missing invoice or transaction reference ID.",
        })
        has_critical_failure = True
    else:
        # Duplicate Reference Check across other cases (Rule G)
        other_results = db.scalars(
            select(ValidationResult).where(
                ValidationResult.recovery_case_id != case.id,
                ValidationResult.passed.is_(True),
            )
        ).all()
        is_duplicate = False
        for vr in other_results:
            if vr.details and f'"invoice_reference": "{invoice_ref}"' in vr.details:
                is_duplicate = True
                break

        if is_duplicate:
            checks.append({
                "name": "duplicate_reference_check",
                "status": "FAIL",
                "message": f"Duplicate invoice reference '{invoice_ref}' has already been validated in another case.",
            })
            has_critical_failure = True
        else:
            checks.append({
                "name": "invoice_reference_check",
                "status": "PASS",
                "message": f"Invoice reference '{invoice_ref}' is present and unique.",
            })

    # 2. Financial Reconciliation: Amount Match (Rule A)
    raw_amount = submission_data.get("invoice_amount")
    if raw_amount is None or str(raw_amount).strip() == "":
        checks.append({
            "name": "amount_match",
            "status": "FAIL",
            "message": "Invoice amount was not provided or could not be determined.",
        })
        has_ambiguity_or_review = True
    else:
        try:
            invoice_amount = Decimal(str(raw_amount))
            payment_amount = Decimal(str(transaction.amount))
            if invoice_amount == payment_amount:
                checks.append({
                    "name": "amount_match",
                    "status": "PASS",
                    "message": f"Payment amount ({payment_amount} {transaction.currency}) matches invoice amount ({invoice_amount} {transaction.currency}).",
                })
            else:
                checks.append({
                    "name": "amount_match",
                    "status": "FAIL",
                    "message": f"Financial mismatch: payment amount is {payment_amount} {transaction.currency} but submitted invoice amount is {invoice_amount} {transaction.currency}.",
                })
                has_critical_failure = True
        except (InvalidOperation, TypeError, ValueError):
            checks.append({
                "name": "amount_match",
                "status": "FAIL",
                "message": f"Invoice amount '{raw_amount}' is not a valid monetary number.",
            })
            has_critical_failure = True

    # 3. Currency Match (Rule B)
    invoice_currency = (submission_data.get("invoice_currency") or "").strip().upper()
    payment_currency = (transaction.currency or "INR").strip().upper()
    if not invoice_currency:
        checks.append({
            "name": "currency_match",
            "status": "FAIL",
            "message": "Invoice currency was not specified.",
        })
        has_ambiguity_or_review = True
    elif invoice_currency == payment_currency:
        checks.append({
            "name": "currency_match",
            "status": "PASS",
            "message": f"Payment currency ({payment_currency}) matches invoice currency ({invoice_currency}).",
        })
    else:
        checks.append({
            "name": "currency_match",
            "status": "FAIL",
            "message": f"Currency mismatch: payment currency is {payment_currency} but invoice currency is {invoice_currency}.",
        })
        has_critical_failure = True

    # 4. Customer Identity Information (Rule D)
    cust_name = submission_data.get("customer_name") or (customer.name if customer else None)
    cust_email = submission_data.get("customer_email") or (customer.email if customer else None)
    cust_country = submission_data.get("country_code") or (customer.country_code if customer else None)

    missing_cust_fields = []
    if not cust_name:
        missing_cust_fields.append("name")
    if not cust_email:
        missing_cust_fields.append("email")
    if not cust_country:
        missing_cust_fields.append("country_code")

    if missing_cust_fields:
        checks.append({
            "name": "customer_information",
            "status": "FAIL",
            "message": f"Customer information is incomplete (missing: {', '.join(missing_cust_fields)}).",
        })
        has_ambiguity_or_review = True
    else:
        checks.append({
            "name": "customer_information",
            "status": "PASS",
            "message": f"Customer identity information is complete ({cust_name}, {cust_email}, {cust_country}).",
        })

    # 5. Document Validation (Rule E)
    require_doc = case.next_best_action == "REQUEST_DOCUMENT" or submission_data.get("require_document", True)
    doc_res = validate_case_documents(case.id, db, require_document=require_doc)
    checks.append({
        "name": doc_res["name"],
        "status": doc_res["status"],
        "message": doc_res["message"],
    })
    if doc_res["status"] == "FAIL":
        if require_doc:
            has_critical_failure = True
        else:
            has_ambiguity_or_review = True

    # 6. Date Validation if provided (Rule F)
    invoice_date_raw = submission_data.get("invoice_date")
    if invoice_date_raw:
        try:
            if isinstance(invoice_date_raw, str):
                inv_dt = datetime.fromisoformat(invoice_date_raw.replace("Z", "+00:00"))
            else:
                inv_dt = invoice_date_raw
            if inv_dt > datetime.now(UTC):
                checks.append({
                    "name": "date_validity",
                    "status": "FAIL",
                    "message": f"Invoice date '{invoice_date_raw}' is in the future.",
                })
                has_critical_failure = True
            else:
                checks.append({
                    "name": "date_validity",
                    "status": "PASS",
                    "message": f"Invoice date '{invoice_date_raw}' is valid.",
                })
        except Exception:
            checks.append({
                "name": "date_validity",
                "status": "FAIL",
                "message": f"Invoice date '{invoice_date_raw}' is not a valid ISO date.",
            })
            has_ambiguity_or_review = True

    # Determine overall status
    if has_critical_failure:
        overall_status = "FAIL"
        overall_reason = "Critical financial or identity inconsistency detected during deterministic validation."
    elif has_ambiguity_or_review:
        overall_status = "REVIEW"
        overall_reason = "Information is partially incomplete or ambiguous; merchant review is required."
    else:
        overall_status = "PASS"
        overall_reason = "All critical deterministic validation checks passed successfully."

    return {
        "status": overall_status,
        "checks": checks,
        "overall_reason": overall_reason,
    }
