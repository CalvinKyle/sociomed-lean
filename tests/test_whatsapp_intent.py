import pytest

from app.services.whatsapp_intent import BuyerIntent, classify_entry_intent, extract_quantity
from app.services.procurement_policy import should_notify_sales


PRODUCTS = [
    {"product_id": "p1", "name": "Surgical Gloves", "category": "consumables"},
    {"product_id": "p2", "name": "IV Set", "category": "consumables"},
    {"product_id": "p3", "name": "Patient Monitor", "category": "equipment"},
]
ALIASES = [
    {"alias": "gloves", "product_id": "p1"},
    {"alias": "drip set", "product_id": "p2"},
]
CATEGORIES = ["consumables", "equipment"]
DATA = {"products": PRODUCTS, "aliases": ALIASES, "inventory": []}


@pytest.mark.parametrize(
    ("message", "navigation"),
    [
        ("1", "search"),
        ("SEARCH", "search"),
        ("2", "categories"),
        ("CATEGORIES", "categories"),
        ("3", "quote"),
        ("QUOTE", "quote"),
        ("4", "sales"),
        ("SALES", "sales"),
        ("0", "menu"),
        ("BACK", "menu"),
    ],
)
def test_global_navigation_aliases(message, navigation):
    result = classify_entry_intent(message, PRODUCTS, ALIASES, CATEGORIES, data=DATA)
    assert result.intent == BuyerIntent.NAVIGATION
    assert result.navigation == navigation


def test_product_with_quantity_is_extracted_on_first_message():
    result = classify_entry_intent(
        "I need 10 boxes of surgical gloves",
        PRODUCTS,
        ALIASES,
        CATEGORIES,
        data=DATA,
    )
    assert result.intent == BuyerIntent.PRODUCT_WITH_QUANTITY
    assert result.quantity == 10
    assert result.uom == "boxes"
    assert result.product["product_id"] == "p1"


def test_formal_purchase_has_priority_over_product_search():
    result = classify_entry_intent(
        "Please prepare a formal quote for surgical gloves",
        PRODUCTS,
        ALIASES,
        CATEGORIES,
        data=DATA,
    )
    assert result.intent == BuyerIntent.FORMAL_PURCHASE


def test_multiple_catalog_items_are_detected():
    result = classify_entry_intent(
        "surgical gloves x10 and IV set x20",
        PRODUCTS,
        ALIASES,
        CATEGORIES,
        data=DATA,
    )
    assert result.intent == BuyerIntent.MULTI_ITEM


def test_category_and_greeting_are_distinct():
    category = classify_entry_intent(
        "browse equipment",
        PRODUCTS,
        ALIASES,
        CATEGORIES,
        data=DATA,
    )
    greeting = classify_entry_intent("hello", PRODUCTS, ALIASES, CATEGORIES, data=DATA)
    assert category.intent == BuyerIntent.CATEGORY
    assert category.category == "equipment"
    assert greeting.intent == BuyerIntent.GREETING


def test_medicines_are_rejected_before_catalog_search():
    result = classify_entry_intent(
        "I need amoxicillin capsules",
        PRODUCTS,
        ALIASES,
        CATEGORIES,
        data=DATA,
    )
    assert result.intent == BuyerIntent.RESTRICTED_MEDICINE


def test_unknown_message_has_safe_fallback():
    result = classify_entry_intent("???", PRODUCTS, ALIASES, CATEGORIES, data=DATA)
    assert result.intent == BuyerIntent.UNKNOWN


@pytest.mark.parametrize(
    ("context", "expected"),
    [
        ({"reason": "market_intelligence"}, False),
        ({"reason": "formal_purchase"}, True),
        ({"reason": "sales_handoff"}, True),
        ({"item_count": 2}, True),
        ({"equipment_review_required": True}, True),
    ],
)
def test_sales_notification_policy(context, expected):
    assert should_notify_sales(context) is expected


def test_extract_quantity_supports_x_notation():
    assert extract_quantity("gloves x25") == (25, None)
