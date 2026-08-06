"""Fail-closed quantity-tier pricing used by every quotation path."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable


@dataclass(frozen=True)
class PriceResolution:
    eligible: bool
    unit_price: int | None
    currency: str
    pricing_id: str | None
    reason_code: str | None
    detail: str | None


@dataclass(frozen=True)
class PricingTierValidation:
    valid: bool
    normalized_tiers: tuple[dict[str, Any], ...]
    reason_code: str | None = None
    detail: str | None = None


def _is_positive_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def validate_pricing_tiers(pricing_tiers: Iterable[dict] | None) -> PricingTierValidation:
    """Validate and normalize inclusive quantity tiers without guessing intent."""
    if not pricing_tiers:
        return PricingTierValidation(False, (), "missing_pricing_tiers", "No pricing tiers were supplied.")

    normalized: list[dict[str, Any]] = []
    for index, raw_tier in enumerate(pricing_tiers):
        if not isinstance(raw_tier, dict):
            return PricingTierValidation(
                False,
                (),
                "invalid_pricing_tier",
                f"Tier {index + 1} is not an object.",
            )

        minimum = raw_tier.get("min_qty")
        maximum = raw_tier.get("max_qty")
        unit_price = raw_tier.get("unit_price")

        if not _is_positive_int(minimum):
            return PricingTierValidation(
                False,
                (),
                "invalid_quantity_bounds",
                f"Tier {index + 1} has an invalid min_qty.",
            )
        if maximum is not None and not _is_positive_int(maximum):
            return PricingTierValidation(
                False,
                (),
                "invalid_quantity_bounds",
                f"Tier {index + 1} has an invalid max_qty.",
            )
        if maximum is not None and maximum < minimum:
            return PricingTierValidation(
                False,
                (),
                "invalid_quantity_bounds",
                f"Tier {index + 1} has max_qty below min_qty.",
            )
        if not _is_positive_int(unit_price):
            return PricingTierValidation(
                False,
                (),
                "invalid_unit_price",
                f"Tier {index + 1} has a missing or invalid unit price.",
            )

        normalized.append(
            {
                **raw_tier,
                "min_qty": minimum,
                "max_qty": maximum,
                "unit_price": unit_price,
                "pricing_id": str(raw_tier.get("pricing_id")) if raw_tier.get("pricing_id") else None,
            }
        )

    normalized.sort(
        key=lambda tier: (
            tier["min_qty"],
            tier["max_qty"] if tier["max_qty"] is not None else float("inf"),
            tier["pricing_id"] or "",
        )
    )

    previous = normalized[0]
    for current in normalized[1:]:
        previous_maximum = previous["max_qty"]
        if previous_maximum is None or current["min_qty"] <= previous_maximum:
            return PricingTierValidation(
                False,
                tuple(normalized),
                "overlapping_pricing_tiers",
                "Two or more pricing tiers cover the same quantity.",
            )
        if current["min_qty"] != previous_maximum + 1:
            return PricingTierValidation(
                False,
                tuple(normalized),
                "pricing_tier_gap",
                "Pricing tiers contain an uncovered quantity gap.",
            )
        previous = current

    return PricingTierValidation(True, tuple(normalized))


def resolve_price_for_quantity(
    pricing_tiers: list[dict],
    quantity: int,
    currency: str,
) -> PriceResolution:
    """Resolve one unambiguous persisted tier price for an exact quantity."""
    normalized_currency = str(currency or "").strip().upper()
    if not _is_positive_int(quantity):
        return PriceResolution(
            False,
            None,
            normalized_currency,
            None,
            "invalid_quantity",
            "Quantity must be a positive whole number.",
        )
    if not normalized_currency:
        return PriceResolution(
            False,
            None,
            "",
            None,
            "missing_currency",
            "Currency is required for price resolution.",
        )

    validation = validate_pricing_tiers(pricing_tiers)
    if not validation.valid:
        return PriceResolution(
            False,
            None,
            normalized_currency,
            None,
            validation.reason_code,
            validation.detail,
        )

    matches = [
        tier
        for tier in validation.normalized_tiers
        if quantity >= tier["min_qty"]
        and (tier["max_qty"] is None or quantity <= tier["max_qty"])
    ]
    if not matches:
        return PriceResolution(
            False,
            None,
            normalized_currency,
            None,
            "no_applicable_pricing_tier",
            "The requested quantity is not covered by a valid pricing tier.",
        )
    if len(matches) != 1:
        return PriceResolution(
            False,
            None,
            normalized_currency,
            None,
            "ambiguous_pricing_tier",
            "The requested quantity matches more than one pricing tier.",
        )

    match = matches[0]
    return PriceResolution(
        True,
        match["unit_price"],
        normalized_currency,
        match["pricing_id"],
        None,
        None,
    )
