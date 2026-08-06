"""Validated merchant identity and commercial terms sourced only from environment."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass


def _json_string_list(variable_name: str) -> tuple[tuple[str, ...], str | None]:
    raw_value = os.getenv(variable_name, "[]")
    try:
        parsed = json.loads(raw_value)
    except (TypeError, json.JSONDecodeError):
        return (), f"{variable_name} must be a JSON array of strings"
    if not isinstance(parsed, list) or any(not isinstance(item, str) for item in parsed):
        return (), f"{variable_name} must be a JSON array of strings"
    return tuple(item.strip() for item in parsed if item.strip()), None


def _positive_int(variable_name: str, default: int) -> tuple[int, str | None]:
    raw_value = os.getenv(variable_name, str(default))
    try:
        value = int(raw_value)
    except (TypeError, ValueError):
        return default, f"{variable_name} must be a positive whole number"
    if value <= 0:
        return default, f"{variable_name} must be a positive whole number"
    return value, None


@dataclass(frozen=True)
class MerchantConfig:
    legal_name: str
    trading_name: str
    tagline: str
    address_lines: tuple[str, ...]
    phone_lines: tuple[str, ...]
    email: str
    website: str
    tax_id: str
    vat_wording: str
    bank_name: str
    bank_account_name: str
    bank_account_number: str
    bank_branch: str
    bank_swift: str
    validity_days: int
    payment_terms: str
    delivery_terms: str
    consumables_warranty: str
    equipment_warranty: str
    equipment_installation: str
    technical_support: str
    configuration_errors: tuple[str, ...] = ()

    @property
    def display_name(self) -> str:
        return self.trading_name or self.legal_name

    @property
    def missing_required_fields(self) -> tuple[str, ...]:
        missing: list[str] = []
        required_scalars = {
            "MERCHANT_LEGAL_NAME": self.legal_name,
            "MERCHANT_TRADING_NAME": self.trading_name,
            "MERCHANT_EMAIL": self.email,
            "MERCHANT_VAT_WORDING": self.vat_wording,
            "MERCHANT_BANK_NAME": self.bank_name,
            "MERCHANT_BANK_ACCOUNT_NAME": self.bank_account_name,
            "MERCHANT_BANK_ACCOUNT_NUMBER": self.bank_account_number,
            "PFI_PAYMENT_TERMS": self.payment_terms,
            "PFI_DELIVERY_TERMS": self.delivery_terms,
        }
        for variable_name, value in required_scalars.items():
            if not str(value or "").strip():
                missing.append(variable_name)
        if not self.address_lines:
            missing.append("MERCHANT_ADDRESS_LINES_JSON")
        if not self.phone_lines:
            missing.append("MERCHANT_PHONE_LINES_JSON")
        return tuple(missing)

    @property
    def is_complete(self) -> bool:
        return not self.missing_required_fields and not self.configuration_errors


def get_merchant_config() -> MerchantConfig:
    address_lines, address_error = _json_string_list("MERCHANT_ADDRESS_LINES_JSON")
    phone_lines, phone_error = _json_string_list("MERCHANT_PHONE_LINES_JSON")
    validity_days, validity_error = _positive_int("PFI_VALIDITY_DAYS", 14)
    errors = tuple(error for error in (address_error, phone_error, validity_error) if error)
    return MerchantConfig(
        legal_name=os.getenv("MERCHANT_LEGAL_NAME", "").strip(),
        trading_name=os.getenv("MERCHANT_TRADING_NAME", "").strip(),
        tagline=os.getenv("MERCHANT_TAGLINE", "").strip(),
        address_lines=address_lines,
        phone_lines=phone_lines,
        email=os.getenv("MERCHANT_EMAIL", "").strip(),
        website=os.getenv("MERCHANT_WEBSITE", "").strip(),
        tax_id=os.getenv("MERCHANT_TAX_ID", "").strip(),
        vat_wording=os.getenv("MERCHANT_VAT_WORDING", "").strip(),
        bank_name=os.getenv("MERCHANT_BANK_NAME", "").strip(),
        bank_account_name=os.getenv("MERCHANT_BANK_ACCOUNT_NAME", "").strip(),
        bank_account_number=os.getenv("MERCHANT_BANK_ACCOUNT_NUMBER", "").strip(),
        bank_branch=os.getenv("MERCHANT_BANK_BRANCH", "").strip(),
        bank_swift=os.getenv("MERCHANT_BANK_SWIFT", "").strip(),
        validity_days=validity_days,
        payment_terms=os.getenv("PFI_PAYMENT_TERMS", "").strip(),
        delivery_terms=os.getenv("PFI_DELIVERY_TERMS", "").strip(),
        consumables_warranty=os.getenv("PFI_CONSUMABLES_WARRANTY", "").strip(),
        equipment_warranty=os.getenv("PFI_EQUIPMENT_WARRANTY", "").strip(),
        equipment_installation=os.getenv("PFI_EQUIPMENT_INSTALLATION", "").strip(),
        technical_support=os.getenv("PFI_TECHNICAL_SUPPORT", "").strip(),
        configuration_errors=errors,
    )
