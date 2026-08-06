"""Explicit, deterministic policy for automated proforma-invoice issuance."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from app.core.merchant import MerchantConfig


PFI_APPROVED_STAGES = {"approval_stage", "ready_to_purchase"}
AUTO_PFI_STOCK_STATUSES = {"verified_in_stock"}


@dataclass(frozen=True)
class PFIEligibilityResult:
    eligible: bool
    requires_manual_review: bool
    reason_codes: tuple[str, ...]
    buyer_message: str
    internal_message: str


def _has_text(value) -> bool:
    return bool(str(value or "").strip())


def evaluate_pfi_eligibility(
    rfq,
    line_items: Iterable,
    merchant_config: MerchantConfig,
) -> PFIEligibilityResult:
    """Return every reason an RFQ cannot safely receive an automated PFI."""
    items = list(line_items)
    reasons: list[str] = []

    stage = str(getattr(rfq, "procurement_stage", "") or "").strip().lower()
    if stage == "budgeting":
        reasons.append("budgeting_only")
    elif stage == "tender":
        reasons.append("tender_request")
    elif stage == "market_sourcing":
        reasons.append("market_sourcing")
    elif stage not in PFI_APPROVED_STAGES:
        reasons.append("procurement_stage_not_approved")

    if not _has_text(getattr(rfq, "buyer_name", None)):
        reasons.append("missing_buyer_name")
    if not _has_text(getattr(rfq, "organization", None)):
        reasons.append("missing_buyer_organization")
    if not _has_text(getattr(rfq, "phone", None)):
        reasons.append("missing_buyer_phone")
    if not _has_text(getattr(rfq, "delivery_location", None)):
        reasons.append("missing_delivery_location")
    if not _has_text(getattr(rfq, "currency", None)):
        reasons.append("missing_currency")
    if not items:
        reasons.append("missing_line_items")

    for index, item in enumerate(items, start=1):
        suffix = f"_line_{index}"
        quantity = getattr(item, "quantity", None)
        unit_price = getattr(item, "unit_price", None)
        line_total = getattr(item, "line_total", None)
        if not isinstance(quantity, int) or isinstance(quantity, bool) or quantity <= 0:
            reasons.append(f"invalid_quantity{suffix}")
        if not _has_text(getattr(item, "uom", None)):
            reasons.append(f"missing_uom{suffix}")
        if not isinstance(unit_price, int) or isinstance(unit_price, bool) or unit_price <= 0:
            reasons.append(f"missing_or_invalid_price{suffix}")
        if not isinstance(line_total, int) or isinstance(line_total, bool) or line_total <= 0:
            reasons.append(f"missing_or_invalid_total{suffix}")
        elif isinstance(quantity, int) and isinstance(unit_price, int) and line_total != quantity * unit_price:
            reasons.append(f"line_total_mismatch{suffix}")
        if not _has_text(getattr(item, "currency", None)):
            reasons.append(f"missing_currency{suffix}")
        elif _has_text(getattr(rfq, "currency", None)) and item.currency.upper() != rfq.currency.upper():
            reasons.append(f"currency_mismatch{suffix}")
        if not _has_text(getattr(item, "price_source", None)):
            reasons.append(f"missing_price_source{suffix}")

        stock_status = str(getattr(item, "stock_verification_status", "") or "").strip().lower()
        if stock_status not in AUTO_PFI_STOCK_STATUSES:
            reasons.append(
                f"partner_stock_confirmation_required{suffix}"
                if stock_status == "partner_confirmation_required"
                else f"stock_not_verified{suffix}"
            )
        if not bool(getattr(item, "is_own_inventory", False)):
            reasons.append(f"partner_inventory{suffix}")

    if bool(getattr(rfq, "requires_credit", False)):
        reasons.append("credit_request")
    if bool(getattr(rfq, "technical_review_required", False)):
        reasons.append("technical_review_required")
    if bool(getattr(rfq, "special_fulfilment_required", False)):
        reasons.append("special_fulfilment_required")
    if bool(getattr(rfq, "manual_review_required", False)):
        manual_reason = str(getattr(rfq, "manual_review_reason", "") or "").strip()
        reasons.append(manual_reason or "manual_review_required")

    if not merchant_config.is_complete:
        reasons.append("merchant_configuration_incomplete")

    unique_reasons = tuple(dict.fromkeys(reasons))
    if unique_reasons:
        return PFIEligibilityResult(
            eligible=False,
            requires_manual_review=True,
            reason_codes=unique_reasons,
            buyer_message=(
                "We have captured your request, but a sales specialist must verify it before a formal PFI can be issued."
            ),
            internal_message="Automated PFI blocked: " + ", ".join(unique_reasons),
        )

    return PFIEligibilityResult(
        eligible=True,
        requires_manual_review=False,
        reason_codes=(),
        buyer_message="Your request qualifies for a formal PFI.",
        internal_message="Automated PFI policy passed.",
    )
