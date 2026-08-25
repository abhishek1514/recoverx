"""Centralized country and currency mappings and validation utilities for RecoverX."""

from __future__ import annotations
from typing import TypedDict


class CountryInfo(TypedDict):
    code: str
    name: str
    default_currency: str
    flag: str


COUNTRY_REGISTRY: dict[str, CountryInfo] = {
    "IN": {"code": "IN", "name": "India", "default_currency": "INR", "flag": "🇮🇳"},
    "US": {"code": "US", "name": "United States", "default_currency": "USD", "flag": "🇺🇸"},
    "CA": {"code": "CA", "name": "Canada", "default_currency": "CAD", "flag": "🇨🇦"},
    "GB": {"code": "GB", "name": "United Kingdom", "default_currency": "GBP", "flag": "🇬🇧"},
    "DE": {"code": "DE", "name": "Germany", "default_currency": "EUR", "flag": "🇩🇪"},
    "FR": {"code": "FR", "name": "France", "default_currency": "EUR", "flag": "🇫🇷"},
    "IT": {"code": "IT", "name": "Italy", "default_currency": "EUR", "flag": "🇮🇹"},
    "ES": {"code": "ES", "name": "Spain", "default_currency": "EUR", "flag": "🇪🇸"},
    "NL": {"code": "NL", "name": "Netherlands", "default_currency": "EUR", "flag": "🇳🇱"},
    "JP": {"code": "JP", "name": "Japan", "default_currency": "JPY", "flag": "🇯🇵"},
    "CN": {"code": "CN", "name": "China", "default_currency": "CNY", "flag": "🇨🇳"},
    "SG": {"code": "SG", "name": "Singapore", "default_currency": "SGD", "flag": "🇸🇬"},
    "AU": {"code": "AU", "name": "Australia", "default_currency": "AUD", "flag": "🇦🇺"},
    "NZ": {"code": "NZ", "name": "New Zealand", "default_currency": "NZD", "flag": "🇳🇿"},
    "CH": {"code": "CH", "name": "Switzerland", "default_currency": "CHF", "flag": "🇨🇭"},
    "AE": {"code": "AE", "name": "United Arab Emirates", "default_currency": "AED", "flag": "🇦🇪"},
    "SA": {"code": "SA", "name": "Saudi Arabia", "default_currency": "SAR", "flag": "🇸🇦"},
    "HK": {"code": "HK", "name": "Hong Kong", "default_currency": "HKD", "flag": "🇭🇰"},
}

# Recognized ISO 4217 currencies
SUPPORTED_CURRENCIES: set[str] = {
    "INR", "USD", "EUR", "GBP", "CAD", "JPY", "CNY", "SGD", "AUD",
    "NZD", "CHF", "AED", "SAR", "HKD", "SEK", "NOK", "DKK", "KRW",
    "BRL", "MXN", "ZAR", "TRY", "PLN", "THB", "IDR", "MYR", "PHP", "VND",
}


def get_default_currency_for_country(country_code: str) -> str | None:
    """Return the primary domestic currency for an ISO country code."""
    c = COUNTRY_REGISTRY.get(country_code.upper().strip())
    return c["default_currency"] if c else None


def is_valid_country(country_code: str) -> bool:
    """Check if the provided country code is in our recognized ISO country registry."""
    return country_code.upper().strip() in COUNTRY_REGISTRY


def is_valid_currency(currency_code: str) -> bool:
    """Check if the provided currency code is a recognized ISO 4217 currency."""
    return currency_code.upper().strip() in SUPPORTED_CURRENCIES


def check_country_currency_alignment(country_code: str, currency_code: str) -> dict[str, str | bool]:
    """Check if the selected currency aligns with the domestic country currency."""
    country = country_code.upper().strip()
    curr = currency_code.upper().strip()
    default_curr = get_default_currency_for_country(country)
    
    is_mismatch = (default_curr is not None and default_curr != curr)
    note = (
        f"Customer country ({country}) differs from transaction currency ({curr})."
        if is_mismatch
        else "Domestic currency aligned."
    )
    return {
        "is_mismatch": is_mismatch,
        "default_currency": default_curr or "",
        "note": note,
    }
