"""Price-verification gate.

Buyers may only be shown prices that the SocioMed team has verified. Every
price tier carries a `price_status` synced from the catalogue sheet. Anything
other than the exact word ``verified`` (including a missing column) is treated
as unverified and the buyer sees "Price on quotation" instead of a number.

The gate fails closed: unknown status, non-positive price, or an unreadable /
expired `price_valid_until` all hide the price.
"""

from datetime import date, datetime
from typing import Mapping, Optional

VERIFIED = "verified"
UNVERIFIED = "unverified"
PRICE_ON_QUOTATION = "Price on quotation"


def normalize_price_status(value: object) -> str:
    """Return ``verified`` only for the exact word (any case); otherwise ``unverified``."""
    return VERIFIED if str(value or "").strip().casefold() == VERIFIED else UNVERIFIED


def parse_valid_until(value: object) -> Optional[date]:
    """Parse a validity date from a date, datetime or ISO string.

    Returns None when no date is set. Raises ValueError when a value is present
    but unreadable so callers can fail closed.
    """
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value).strip()[:10])


def _is_positive(value: object) -> bool:
    try:
        return float(str(value).replace(",", "").strip()) > 0
    except (TypeError, ValueError):
        return False


def is_price_displayable(tier: Mapping[str, object], today: Optional[date] = None) -> bool:
    """True only for a verified, positive, unexpired price tier."""
    if normalize_price_status(tier.get("price_status")) != VERIFIED:
        return False
    if not _is_positive(tier.get("unit_price")):
        return False
    try:
        valid_until = parse_valid_until(tier.get("price_valid_until"))
    except ValueError:
        return False
    return valid_until is None or valid_until >= (today or date.today())


def displayable_tiers(tiers: list[dict], today: Optional[date] = None) -> list[dict]:
    """Return the tier ladder if *every* tier is displayable, otherwise nothing.

    A partly verified ladder would show a misleading "from" price, so verification
    is all-or-nothing per offer.
    """
    if tiers and all(is_price_displayable(tier, today) for tier in tiers):
        return list(tiers)
    return []
