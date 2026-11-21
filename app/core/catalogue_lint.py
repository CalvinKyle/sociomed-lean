"""Pre-sync catalogue lint: finds price and link problems before buyers see them.

Pure functions over the same row dicts the sync uses (sheet rows or DB rows).
Findings never block a sync; they are logged and printed by
``scripts/lint_catalogue.py`` so the team knows what to verify or fix.
"""

from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import date
from typing import Iterable, Mapping, Optional

from app.core.pricing import VERIFIED, is_price_displayable, normalize_price_status

SPREAD_WARNING_RATIO = 10.0

ERROR = "error"
WARNING = "warning"
INFO = "info"


@dataclass(frozen=True)
class LintFinding:
    severity: str
    code: str
    entity_id: str
    message: str


@dataclass
class LintReport:
    findings: list[LintFinding] = field(default_factory=list)
    stats: dict[str, int] = field(default_factory=dict)

    @property
    def counts(self) -> Counter:
        return Counter(finding.code for finding in self.findings)

    @property
    def has_errors(self) -> bool:
        return any(finding.severity == ERROR for finding in self.findings)

    def summary_line(self) -> str:
        parts = ", ".join(f"{code}={count}" for code, count in sorted(self.counts.items()))
        verified = self.stats.get("offers_fully_verified", 0)
        total = self.stats.get("offers_with_pricing", 0)
        return f"{verified}/{total} priced offers are fully verified; findings: {parts or 'none'}"

    def format(self, limit_per_code: int = 15) -> str:
        lines = [self.summary_line(), ""]
        shown: Counter = Counter()
        for finding in sorted(self.findings, key=lambda f: (f.severity != ERROR, f.code, f.entity_id)):
            shown[finding.code] += 1
            if shown[finding.code] > limit_per_code:
                continue
            lines.append(f"[{finding.severity.upper():7}] {finding.code:24} {finding.entity_id}: {finding.message}")
        for code, count in sorted(self.counts.items()):
            if count > limit_per_code:
                lines.append(f"... {count - limit_per_code} more {code} findings not shown")
        return "\n".join(lines)


def _number(value: object) -> Optional[float]:
    try:
        number = float(str(value).replace(",", "").strip())
    except (TypeError, ValueError):
        return None
    return number


def _text(value: object) -> str:
    return str(value).strip() if value not in (None, "") else ""


def lint_catalogue(
    data: Mapping[str, Iterable[Mapping[str, object]]],
    today: Optional[date] = None,
) -> LintReport:
    """Lint products/inventory/pricing rows. Never raises on bad data."""
    products = {_text(row.get("product_id")): row for row in data.get("products", [])}
    inventory = {_text(row.get("inventory_id")): row for row in data.get("inventory", [])}
    pricing = list(data.get("pricing", []))
    report = LintReport()

    def add(severity: str, code: str, entity_id: str, message: str) -> None:
        report.findings.append(LintFinding(severity, code, entity_id, message))

    tiers_by_inventory: dict[str, list[Mapping[str, object]]] = defaultdict(list)
    for row in pricing:
        inventory_id = _text(row.get("inventory_id"))
        label = _text(row.get("pricing_id")) or f"{inventory_id or '?'} (no pricing_id)"
        if not _text(row.get("pricing_id")):
            add(ERROR, "missing_pricing_id", label, "pricing row has no pricing_id; the sync will skip it")
        if inventory_id not in inventory:
            add(ERROR, "orphan_pricing", label, f"inventory_id {inventory_id or '(blank)'} does not exist")
            continue
        price = _number(row.get("unit_price"))
        if price is None or price <= 0:
            add(ERROR, "missing_price", label, "unit_price is blank or not positive")
            continue
        tiers_by_inventory[inventory_id].append(row)

    report.stats["offers_with_pricing"] = len(tiers_by_inventory)
    verified_offers = 0
    for inventory_id, tiers in tiers_by_inventory.items():
        statuses = {normalize_price_status(tier.get("price_status")) for tier in tiers}
        if statuses == {VERIFIED}:
            verified_offers += 1
            if not all(is_price_displayable(tier, today) for tier in tiers):
                add(WARNING, "verified_but_expired", inventory_id, "verified price is past price_valid_until or unreadable; buyers will see 'Price on quotation'")
        elif VERIFIED in statuses:
            add(WARNING, "partially_verified", inventory_id, "some tiers verified, some not; buyers see no price until all tiers are verified")

        ordered = sorted(tiers, key=lambda tier: _number(tier.get("min_qty")) or 0)
        prices = [_number(tier.get("unit_price")) or 0 for tier in ordered]
        if any(later > earlier for earlier, later in zip(prices, prices[1:])):
            add(WARNING, "tier_price_increases", inventory_id, "price rises with quantity: " + " -> ".join(f"{p:,.0f}" for p in prices))
    report.stats["offers_fully_verified"] = verified_offers

    # Same product family and pack size should cost roughly the same order of magnitude.
    groups: dict[tuple[str, str], list[tuple[float, str]]] = defaultdict(list)
    for inventory_id, tiers in tiers_by_inventory.items():
        item = inventory[inventory_id]
        product = products.get(_text(item.get("product_id")), {})
        family = _text(product.get("product_family_id")) or _text(item.get("product_id"))
        uom = _text(item.get("uom")) or "unit"
        lowest_tier = min(tiers, key=lambda tier: _number(tier.get("min_qty")) or 0)
        groups[(family, uom)].append((_number(lowest_tier.get("unit_price")) or 0, inventory_id))
    for (family, uom), offers in groups.items():
        if len(offers) < 2:
            continue
        low, high = min(offers), max(offers)
        if low[0] > 0 and high[0] / low[0] >= SPREAD_WARNING_RATIO:
            add(
                WARNING,
                "price_spread",
                f"{family} / {uom}",
                f"{high[0] / low[0]:,.0f}x spread: {low[0]:,.0f} ({low[1]}) vs {high[0]:,.0f} ({high[1]}) — check units/scale",
            )

    if not verified_offers:
        add(INFO, "no_verified_prices", "catalogue", "no offer is fully verified; the bot will show 'Price on quotation' for every product")
    return report
