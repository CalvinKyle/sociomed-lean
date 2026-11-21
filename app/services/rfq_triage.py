import re
from dataclasses import dataclass
from typing import Dict, Mapping, Optional

from app.core.config import SMALL_RFQ_MAX_ITEMS
from app.core.conversation_copy import conversation_message
from app.core.pricing import PRICE_ON_QUOTATION
from app.services.search import find_products, get_results


BULK_MATCH_THRESHOLD = SMALL_RFQ_MAX_ITEMS
MAX_PRODUCT_NAME_LENGTH = 160
ITEM_QUANTITY_PATTERN = re.compile(r"^(.*?)\s*[xX]\s*(\d+)$")


@dataclass(frozen=True)
class DirectRFQPayload:
    buyer_name: str
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


def _parse_item_text(item_text: str) -> tuple[str, int]:
    """Parse a bulk fragment such as 'gloves x10', defaulting quantity to one."""
    match = ITEM_QUANTITY_PATTERN.match(item_text.strip())
    if not match:
        return item_text.strip(), 1
    name, quantity_text = match.groups()
    return name.strip(), int(quantity_text)


def resolve_bulk_line_items(items: list[str], data: dict, currency: str = "UGX") -> list[dict]:
    """Resolve bulk fragments to their best catalog offers without dropping unmatched items."""
    resolved = []
    for item_text in items:
        name_text, quantity = _parse_item_text(item_text)
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
                    "quantity": quantity,
                    "uom": None,
                    "unit_price": None,
                }
            )
            continue

        product = matches[0]
        offers = get_results(product["product_id"], data, currency=currency)
        best_offer = offers[0] if offers else None
        resolved.append(
            {
                "product_id": product["product_id"],
                "product_name": product["name"],
                "vendor_id": best_offer.get("vendor_id") if best_offer else None,
                "vendor_name": best_offer.get("vendor_name") if best_offer else None,
                "quantity": quantity,
                "uom": best_offer.get("uom") if best_offer else None,
                "unit_price": best_offer.get("default_price") if best_offer else None,
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


def parse_direct_rfq_message(
    text: str,
    buyer_profile: Optional[Mapping[str, str]] = None,
) -> Optional[DirectRFQPayload]:
    parts = _split_pipe_message(text)
    if len(parts) == 2 and buyer_profile:
        item_text, quantity_text = parts
        try:
            quantity = int(quantity_text)
        except ValueError:
            return None
        return DirectRFQPayload(
            buyer_name=buyer_profile.get("contact_name", ""),
            product_name=_trim_product_name(item_text),
            quantity=quantity,
            organization=buyer_profile.get("organization", ""),
            delivery_location=buyer_profile.get("delivery_location", ""),
            source="whatsapp_returning_buyer_rfq",
            notes="Buyer confirmed reuse of saved procurement profile",
        )
    if len(parts) >= 5:
        buyer_name, item_text, quantity_text, facility, location = parts[:5]
        try:
            quantity = int(quantity_text)
        except ValueError:
            return None

        items = split_requested_items(item_text)
        if len(items) > 1:
            return DirectRFQPayload(
                buyer_name=buyer_name,
                product_name=_bulk_product_name(items),
                quantity=parse_requested_items(item_text)[0]["quantity"],
                organization=facility,
                delivery_location=location,
                source="whatsapp_bulk_rfq",
                notes=_bulk_notes(items, text),
                is_bulk=True,
                item_count=len(items),
            )

        return DirectRFQPayload(
            buyer_name=buyer_name,
            product_name=_trim_product_name(item_text),
            quantity=quantity,
            organization=facility,
            delivery_location=location,
            source="whatsapp_direct_rfq",
            notes="Generic RFQ from main menu",
        )

    if len(parts) == 4 and is_bulk_request(parts[1]):
        buyer_name, item_text, facility, location = parts
        items = split_requested_items(item_text)
        return DirectRFQPayload(
            buyer_name=buyer_name,
            product_name=_bulk_product_name(items),
            quantity=parse_requested_items(item_text)[0]["quantity"],
            organization=facility,
            delivery_location=location,
            source="whatsapp_bulk_rfq",
            notes=_bulk_notes(items, text),
            is_bulk=True,
            item_count=len(items),
        )

    return None


def format_ambiguous_match_message(matches: list[Dict]) -> str:
    product_list = "\n".join(
        conversation_message(
            "ambiguous_product_row",
            index=index,
            product_name=product.get("search_display_name") or product["name"],
            price_text=product.get("price_text") or PRICE_ON_QUOTATION,
            variant_count=product.get("variant_count", 1),
            offer_count=product.get("offer_count", 0),
        )
        for index, product in enumerate(matches, start=1)
    )
    if len(matches) > BULK_MATCH_THRESHOLD:
        next_step = conversation_message("ambiguous_next_large")
    else:
        next_step = conversation_message("ambiguous_next_small")

    return f"{conversation_message('ambiguous_header')}\n{product_list}\n\n{next_step}"


def parse_requested_items(text: str, products=None) -> list[dict]:
    """Parse quantities without turning item count into a requested quantity."""
    protected = text.strip()
    names = ['bed and mattress', 'gauze and bandage'] + [p.get('name', '') for p in (products or [])]
    for name in sorted(names, key=len, reverse=True):
        if ' and ' in name.lower():
            protected = re.sub(re.escape(name), lambda m: re.sub(r'\band\b', '§', m[0], flags=re.I), protected, flags=re.I)
    parts = re.split(r'\s*(?:[,;+\n]|\band\b)\s*', protected, flags=re.I)
    parsed = []
    for part in parts:
        part = part.replace('§', 'and').strip(' .')
        part = re.sub(r'^(?:i need|we need|i want|please quote|quote for|quotation for)\s+', '', part, flags=re.I)
        if not part:
            continue
        quantity, stated, uom = 1, False, None
        suffix = re.search(r'\s*[xX]\s*(\d+)\s*$', part)
        prefix = re.match(r'^(\d+)\s*(?:[xX]\s+)?(.+)$', part)
        if suffix:
            quantity, stated, part = int(suffix[1]), True, part[:suffix.start()].strip()
        elif prefix:
            quantity, stated, part = int(prefix[1]), True, prefix[2].strip()
        unit = re.match(r'^(boxes?|packs?|cartons?|pieces?|units?|pairs?|sets?|rolls?|bottles?|bags?|kits?)\s+(?:of\s+)?(.+)$', part, re.I)
        if unit:
            uom, part = unit[1].lower(), unit[2].strip()
        if not part or quantity <= 0:
            raise ValueError('Each item needs a name and positive quantity')
        parsed.append({'product_name': part, 'quantity': quantity, 'uom': uom, 'quantity_stated': stated})
    if len(parsed) > 20:
        raise ValueError('Send at most 20 items at a time, in parts, or reply SALES')
    return parsed


def resolve_requested_items(items: list[dict], data: dict, currency='UGX') -> list[dict]:
    from rapidfuzz.fuzz import ratio
    resolved = []
    products = data.get('products', [])
    for item in items:
        name = item['product_name']
        # Strict name/alias matching avoids committing a fuzzy guess as a purchase.
        matches = [p for p in products if ratio(name.lower(), p['name'].lower()) >= 90]
        aliases = {a['product_id'] for a in data.get('aliases', []) if a['alias'].lower() == name.lower()}
        matches += [p for p in products if p['product_id'] in aliases and p not in matches]
        product = matches[0] if len(matches) == 1 else None
        line = {k: item.get(k) for k in ('product_name', 'quantity', 'uom')}
        line.update(product_id=None, unit_price=None)
        if product:
            offers = get_results(product['product_id'], data, currency=currency)
            offer = offers[0] if offers else {}
            line.update(product_id=product['product_id'], product_name=product['name'], vendor_id=offer.get('vendor_id'))
            line['uom'] = item.get('uom') or offer.get('uom')
            # get_results returns only offer-wide verified/unexpired pricing.
            for tier in offer.get('pricing', []):
                if tier['min_qty'] <= item['quantity'] and (tier.get('max_qty') is None or item['quantity'] <= tier['max_qty']):
                    line['unit_price'] = tier['unit_price']
                    break
        resolved.append(line)
    return resolved
