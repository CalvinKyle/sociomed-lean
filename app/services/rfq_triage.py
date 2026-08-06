import re
from dataclasses import dataclass
from typing import Dict, Optional

from app.services.search import find_products, get_results
from app.services.pricing import resolve_price_for_quantity


BULK_MATCH_THRESHOLD = 3
MAX_PRODUCT_NAME_LENGTH = 160
ITEM_QUANTITY_PATTERN = re.compile(r"^(.*?)\s*[xX]\s*(\d+)$")


@dataclass(frozen=True)
class DirectRFQPayload:
    buyer_name: str
    product_name: str
    quantity: int
    organization: str
    delivery_location: str
    procurement_stage: str
    source: str
    notes: Optional[str] = None
    is_bulk: bool = False
    item_count: int = 1
    requested_items: tuple[str, ...] = ()


def split_requested_items(item_text: str) -> list[str]:
    normalized = re.sub(r"\s+", " ", item_text.strip())
    if re.fullmatch(r".+?,\s*\d+\s+[A-Za-z][A-Za-z -]*", normalized):
        return [normalized]
    parts = re.split(r"\s*(?:,|;|\+|\n|\band\b)\s*", normalized, flags=re.IGNORECASE)
    return [part.strip(" .") for part in parts if part.strip(" .")]


def is_bulk_request(item_text: str) -> bool:
    return len(split_requested_items(item_text)) > 1


def is_complex_bulk_request(item_text: str, threshold: int = BULK_MATCH_THRESHOLD) -> bool:
    return len(split_requested_items(item_text)) > threshold


def _parse_item_text(item_text: str, default_quantity: int = 1) -> tuple[str, int]:
    """Parse a bulk fragment such as 'gloves x10', defaulting quantity to one."""
    match = ITEM_QUANTITY_PATTERN.match(item_text.strip())
    if not match:
        return item_text.strip(), default_quantity
    name, quantity_text = match.groups()
    return name.strip(), int(quantity_text)


def resolve_bulk_line_items(
    items: list[str],
    data: dict,
    currency: str = "UGX",
    default_quantity: int = 1,
) -> list[dict]:
    """Resolve bulk fragments to their best catalog offers without dropping unmatched items."""
    resolved = []
    for item_text in items:
        name_text, quantity = _parse_item_text(item_text, default_quantity=default_quantity)
        matches = find_products(
            name_text,
            data.get("products", []),
            data.get("aliases", []),
            limit=1,
            data=data,
        )

        if not matches:
            resolved.append(
                {
                    "product_id": None,
                    "product_name": name_text,
                    "vendor_id": None,
                    "vendor_name": None,
                    "vendor_phone": None,
                    "quantity": quantity,
                    "uom": None,
                    "unit_price": None,
                }
            )
            continue

        product = matches[0]
        offers = get_results(product["product_id"], data, currency=currency)
        best_offer = offers[0] if offers else None
        price_resolution = (
            resolve_price_for_quantity(best_offer.get("pricing", []), quantity, currency)
            if best_offer
            else None
        )
        if best_offer and best_offer.get("is_own_inventory"):
            stock_status = (
                "verified_in_stock"
                if isinstance(best_offer.get("stock_qty"), int) and best_offer["stock_qty"] >= quantity
                else "insufficient_stock"
                if (best_offer.get("stock_qty") or 0) > 0
                else "out_of_stock"
            )
        else:
            stock_status = "partner_confirmation_required" if best_offer else "unknown"
        resolved.append(
            {
                "inventory_id": best_offer.get("inventory_id") if best_offer else None,
                "product_id": product["product_id"],
                "product_name": product["name"],
                "brand": best_offer.get("brand") if best_offer else None,
                "sku": best_offer.get("sku") if best_offer else None,
                "item_type": product.get("item_type") or "generic",
                "vendor_id": best_offer.get("vendor_id") if best_offer else None,
                "vendor_name": best_offer.get("vendor_name") if best_offer else None,
                "vendor_phone": best_offer.get("vendor_phone") if best_offer else None,
                "is_own_inventory": bool(best_offer and best_offer.get("is_own_inventory")),
                "quantity": quantity,
                "uom": best_offer.get("uom") if best_offer else None,
                "unit_price": price_resolution.unit_price if price_resolution and price_resolution.eligible else None,
                "currency": currency,
                "price_source": price_resolution.pricing_id if price_resolution and price_resolution.eligible else None,
                "stock_verification_status": stock_status,
            }
        )
    return resolved


def _split_pipe_message(text: str) -> list[str]:
    return [part.strip() for part in text.split("|") if part.strip()]


def _trim_product_name(name: str) -> str:
    if len(name) <= MAX_PRODUCT_NAME_LENGTH:
        return name
    return f"{name[: MAX_PRODUCT_NAME_LENGTH - 3].rstrip()}..."


def _bulk_product_name(items: list[str]) -> str:
    preview = ", ".join(items[:3])
    suffix = "" if len(items) <= 3 else f", +{len(items) - 3} more"
    return _trim_product_name(f"Bulk RFQ: {preview}{suffix}")


def _bulk_notes(items: list[str], original_text: str) -> str:
    numbered_items = "; ".join(f"{index}. {item}" for index, item in enumerate(items, start=1))
    return f"Bulk RFQ items: {numbered_items}. Original request: {original_text.strip()}"


def parse_direct_rfq_message(text: str) -> Optional[DirectRFQPayload]:
    parts = _split_pipe_message(text)
    if len(parts) in {4, 5} and is_bulk_request(parts[1]):
        buyer_name, item_text, facility, location = parts[:4]
        procurement_stage = normalize_procurement_stage(parts[4]) if len(parts) == 5 else "market_sourcing"
        if not procurement_stage:
            return None
        items = split_requested_items(item_text)
        return DirectRFQPayload(
            buyer_name=buyer_name,
            product_name=_bulk_product_name(items),
            quantity=len(items),
            organization=facility,
            delivery_location=location,
            procurement_stage=procurement_stage,
            source="whatsapp_bulk_rfq",
            notes=_bulk_notes(items, text),
            is_bulk=True,
            item_count=len(items),
            requested_items=tuple(items),
        )

    if len(parts) >= 5:
        buyer_name, item_text, quantity_text, facility, location = parts[:5]
        procurement_stage = normalize_procurement_stage(parts[5]) if len(parts) >= 6 else "market_sourcing"
        if not procurement_stage:
            return None
        try:
            quantity = int(quantity_text)
        except ValueError:
            return None

        items = split_requested_items(item_text)
        if len(items) > 1:
            return DirectRFQPayload(
                buyer_name=buyer_name,
                product_name=_bulk_product_name(items),
                quantity=max(quantity, len(items)),
                organization=facility,
                delivery_location=location,
                procurement_stage=procurement_stage,
                source="whatsapp_bulk_rfq",
                notes=_bulk_notes(items, text),
                is_bulk=True,
                item_count=len(items),
                requested_items=tuple(items),
            )

        return DirectRFQPayload(
            buyer_name=buyer_name,
            product_name=_trim_product_name(item_text),
            quantity=quantity,
            organization=facility,
            delivery_location=location,
            procurement_stage=procurement_stage,
            source="whatsapp_direct_rfq",
            notes="Generic RFQ from main menu",
            requested_items=(item_text,),
        )

    return None


PROCUREMENT_STAGE_ALIASES = {
    "1": "budgeting",
    "budget": "budgeting",
    "budgeting": "budgeting",
    "market research": "budgeting",
    "2": "approval_stage",
    "approval": "approval_stage",
    "awaiting approval": "approval_stage",
    "approval stage": "approval_stage",
    "approval_stage": "approval_stage",
    "3": "ready_to_purchase",
    "ready": "ready_to_purchase",
    "ready to purchase": "ready_to_purchase",
    "ready_to_purchase": "ready_to_purchase",
    "4": "tender",
    "tender": "tender",
    "5": "market_sourcing",
    "market sourcing": "market_sourcing",
    "market_sourcing": "market_sourcing",
    "sourcing": "market_sourcing",
}


def normalize_procurement_stage(value: str) -> str | None:
    normalized = re.sub(r"\s+", " ", str(value or "").strip().lower())
    return PROCUREMENT_STAGE_ALIASES.get(normalized)


def format_ambiguous_match_message(matches: list[Dict]) -> str:
    product_list = "\n".join(f"{index}. {product['name']}" for index, product in enumerate(matches, start=1))
    if len(matches) > BULK_MATCH_THRESHOLD:
        next_step = (
            "Reply with the product number to price one item first.\n"
            "Reply RFQ if this is a bulk request, or AGENT for a sourcing handoff."
        )
    else:
        next_step = "Reply with the product number you want to price first, or RFQ for a quotation."

    return f"I found multiple possible matches:\n{product_list}\n\n{next_step}"
