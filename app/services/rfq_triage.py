import re
from dataclasses import dataclass
from typing import Dict, Optional


BULK_MATCH_THRESHOLD = 3
MAX_PRODUCT_NAME_LENGTH = 160


@dataclass(frozen=True)
class DirectRFQPayload:
    product_name: str
    quantity: int
    organization: str
    delivery_location: str
    source: str
    notes: Optional[str] = None
    is_bulk: bool = False
    item_count: int = 1


def split_requested_items(item_text: str) -> list[str]:
    normalized = re.sub(r"\s+", " ", item_text.strip())
    parts = re.split(r"\s*(?:,|;|\+|\n|\band\b)\s*", normalized, flags=re.IGNORECASE)
    return [part.strip(" .") for part in parts if part.strip(" .")]


def is_bulk_request(item_text: str) -> bool:
    return len(split_requested_items(item_text)) > 1


def is_complex_bulk_request(item_text: str, threshold: int = BULK_MATCH_THRESHOLD) -> bool:
    return len(split_requested_items(item_text)) > threshold


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
    if len(parts) >= 4:
        item_text, quantity_text, facility, location = parts[:4]
        try:
            quantity = int(quantity_text)
        except ValueError:
            return None

        items = split_requested_items(item_text)
        if len(items) > 1:
            return DirectRFQPayload(
                product_name=_bulk_product_name(items),
                quantity=max(quantity, len(items)),
                organization=facility,
                delivery_location=location,
                source="whatsapp_bulk_rfq",
                notes=_bulk_notes(items, text),
                is_bulk=True,
                item_count=len(items),
            )

        return DirectRFQPayload(
            product_name=_trim_product_name(item_text),
            quantity=quantity,
            organization=facility,
            delivery_location=location,
            source="whatsapp_direct_rfq",
            notes="Generic RFQ from main menu",
        )

    if len(parts) == 3 and is_bulk_request(parts[0]):
        item_text, facility, location = parts
        items = split_requested_items(item_text)
        return DirectRFQPayload(
            product_name=_bulk_product_name(items),
            quantity=len(items),
            organization=facility,
            delivery_location=location,
            source="whatsapp_bulk_rfq",
            notes=_bulk_notes(items, text),
            is_bulk=True,
            item_count=len(items),
        )

    return None


def format_ambiguous_match_message(matches: list[Dict]) -> str:
    product_list = "\n".join(f"{index}. {product['name']}" for index, product in enumerate(matches, start=1))
    if len(matches) > BULK_MATCH_THRESHOLD:
        next_step = (
            "Reply with the product number to price one item first.\n"
            "Reply RFQ if this is a bulk request, or AGENT for a sourcing handoff."
        )
    else:
        next_step = "Reply with the product number you want to price first, or RFQ for a manual quotation."

    return f"I found multiple possible matches:\n{product_list}\n\n{next_step}"
