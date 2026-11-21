import re
from dataclasses import dataclass
from enum import Enum
from typing import Optional

from app.services.search import find_products


class BuyerIntent(str, Enum):
    NAVIGATION = "navigation"
    SALES = "sales"
    FORMAL_PURCHASE = "formal_purchase"
    MULTI_ITEM = "multi_item"
    PRODUCT_WITH_QUANTITY = "product_with_quantity"
    PRODUCT = "product"
    CATEGORY = "category"
    GREETING = "greeting"
    STATE_RESPONSE = "state_response"
    RESTRICTED_MEDICINE = "restricted_medicine"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class IntentResult:
    intent: BuyerIntent
    normalized_text: str
    navigation: Optional[str] = None
    quantity: Optional[int] = None
    uom: Optional[str] = None
    product: Optional[dict] = None
    matches: tuple[dict, ...] = ()
    category: Optional[str] = None


NAVIGATION_ALIASES = {
    "0": "menu",
    "menu": "menu",
    "back": "menu",
    "m": "menu",
    "1": "search",
    "search": "search",
    "2": "categories",
    "categories": "categories",
    "category": "categories",
    "3": "quote",
    "quote": "quote",
    "quotation": "quote",
    "rfq": "quote",
    "4": "sales",
    "sales": "sales",
}
GREETING_PATTERN = re.compile(r"^(?:hi|hello|hey|good\s+(?:morning|afternoon|evening)|start|help)[!.\s]*$", re.I)
SALES_PATTERN = re.compile(r"\b(?:sales|agent|human|person|call\s+me|talk\s+to|speak\s+to)\b", re.I)
FORMAL_PURCHASE_PATTERN = re.compile(
    r"\b(?:formal\s+(?:purchase|quote)|purchase\s+order|quotation|quote|rfq|tender|proforma|pfi)\b",
    re.I,
)
MEDICINE_PATTERN = re.compile(
    r"\b(?:medicine|medicines|drug|drugs|tablet|tablets|capsule|capsules|antibiotic|"
    r"amoxicillin|paracetamol|acetaminophen|ibuprofen|metformin|insulin)\b",
    re.I,
)
QUANTITY_PATTERNS = (
    re.compile(r"\bx\s*(\d+)\b", re.I),
    re.compile(
        r"\b(\d+)\s*(boxes?|packs?|cartons?|cases?|pieces?|pcs?|units?|pairs?|sets?|"
        r"rolls?|bottles?|bags?|tubes?|kits?|each)\b",
        re.I,
    ),
)
MULTI_ITEM_SEPARATOR = re.compile(r"(?:,|;|\n|\s+and\s+|\s*\+\s*)", re.I)


def extract_quantity(text: str) -> tuple[Optional[int], Optional[str]]:
    for pattern in QUANTITY_PATTERNS:
        match = pattern.search(text)
        if match:
            quantity = int(match.group(1))
            uom = match.group(2).lower() if match.lastindex and match.lastindex >= 2 else None
            return quantity, uom
    return None, None


def is_restricted_medicine(text: str) -> bool:
    return bool(MEDICINE_PATTERN.search(text))


def _resolve_category(text: str, categories: list[str]) -> Optional[str]:
    normalized = text.strip().lower()
    for category in categories:
        category_clean = category.strip().lower()
        if normalized == category_clean:
            return category
        if re.search(rf"\b{re.escape(category_clean)}\b", normalized) and any(
            word in normalized for word in ("browse", "category", "supplies", "products")
        ):
            return category
    return None


def _product_query(text: str) -> str:
    cleaned = text
    for pattern in QUANTITY_PATTERNS:
        cleaned = pattern.sub(" ", cleaned)
    cleaned = re.sub(
        r"^(?:i\s+(?:need|want|am looking for)|we\s+(?:need|want)|please\s+find|looking for)\s+",
        "",
        cleaned,
        flags=re.I,
    )
    cleaned = re.sub(r"\b(?:of|please|available|availability|price|cost)\b", " ", cleaned)
    return re.sub(r"\s+", " ", cleaned).strip()


def _looks_multi_item(text: str, products: list[dict], aliases: list[dict], data: Optional[dict]) -> bool:
    fragments = [part.strip() for part in MULTI_ITEM_SEPARATOR.split(text) if part.strip()]
    if len(fragments) < 2:
        return False
    matched_fragments = 0
    for fragment in fragments[:8]:
        if find_products(fragment, products, aliases, limit=1, data=data):
            matched_fragments += 1
    return matched_fragments >= 2


def classify_entry_intent(
    text: str,
    products: list[dict],
    aliases: list[dict],
    categories: list[str],
    *,
    data: Optional[dict] = None,
    state_expects_response: bool = False,
) -> IntentResult:
    normalized = re.sub(r"\s+", " ", text.strip().lower())
    navigation = NAVIGATION_ALIASES.get(normalized)
    if navigation:
        return IntentResult(BuyerIntent.NAVIGATION, normalized, navigation=navigation)

    if is_restricted_medicine(normalized):
        return IntentResult(BuyerIntent.RESTRICTED_MEDICINE, normalized)

    if SALES_PATTERN.search(normalized):
        return IntentResult(BuyerIntent.SALES, normalized)

    if FORMAL_PURCHASE_PATTERN.search(normalized):
        return IntentResult(BuyerIntent.FORMAL_PURCHASE, normalized)

    if _looks_multi_item(normalized, products, aliases, data):
        return IntentResult(BuyerIntent.MULTI_ITEM, normalized)

    if GREETING_PATTERN.match(normalized):
        return IntentResult(BuyerIntent.GREETING, normalized)

    category = _resolve_category(normalized, categories)
    if category:
        return IntentResult(BuyerIntent.CATEGORY, normalized, category=category)

    quantity, uom = extract_quantity(normalized)
    matches = find_products(_product_query(normalized), products, aliases, limit=5, data=data)
    if matches:
        intent = BuyerIntent.PRODUCT_WITH_QUANTITY if quantity else BuyerIntent.PRODUCT
        return IntentResult(
            intent,
            normalized,
            quantity=quantity,
            uom=uom,
            product=matches[0] if len(matches) == 1 else None,
            matches=tuple(matches),
        )

    if state_expects_response:
        return IntentResult(BuyerIntent.STATE_RESPONSE, normalized)

    return IntentResult(BuyerIntent.UNKNOWN, normalized)
