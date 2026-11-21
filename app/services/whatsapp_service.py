from app.core.uom import buyer_uom
import logging
import re
from typing import Dict, Optional

from rapidfuzz import fuzz

from app.core.conversation_copy import conversation_message
from app.core.currency import format_price, get_currency_for_phone
from app.core.pricing import PRICE_ON_QUOTATION
from app.core.states import ConversationState
from app.core.utils import get_session, has_seen_before, log_audit_event, save_session, send_whatsapp_message
from app.core.validators import (
    validate_contact_name,
    validate_delivery_location,
    validate_facility_name,
    validate_product_query,
    validate_quantity,
    validate_state,
    validate_whatsapp_message,
)
from app.data_access.catalog import (
    get_categories,
    get_products_by_category,
    get_subcategories_by_category,
    has_browse_menu,
)
from app.data_access.funnel import record_funnel_event
from app.data_access.procurement import get_buyer_profile
from app.models.db import SessionLocal
from app.models.formatter import format_price_range, format_results
from app.schemas.schemas import BuyerLeadCreate, RFQCreate
from app.services.catalog import get_featured_catalog, get_related_catalog
from app.services.procurement import (
    create_buyer_lead,
    create_rfq_request,
    dispatch_lead_notification,
    dispatch_rfq_notifications,
)
from app.services.rfq_triage import (
    format_ambiguous_match_message,
    is_bulk_request,
    is_complex_bulk_request,
    parse_direct_rfq_message,
    parse_requested_items,
    resolve_requested_items,
)
from app.services.search import FAMILY_DISPLAY_NAMES, find_products, get_results
from app.services.procurement_policy import is_equipment_product
from app.services.whatsapp_intent import BuyerIntent, classify_entry_intent
from app.core.cache import get_cached_data

logger = logging.getLogger(__name__)

# Buyer-facing strings are English-only today. This hook makes the current
# assumption observable and provides a routing point for future translations.
SUPPORTED_LANGUAGES = {"en"}
FUZZY_SELECTION_THRESHOLD = 82
FUZZY_SELECTION_MARGIN = 8
END_COMMANDS = frozenset({"end", "done", "close", "close session", "finish", "bye", "goodbye"})
SUBCATEGORY_PAGE_SIZE = 4
PRODUCT_DISPLAY_LIMIT = 12


def _detect_language(sender: str, text: str) -> str:
    """Placeholder for future language detection; English is currently supported."""
    return "en"


def extract_message(body: Dict) -> Optional[Dict]:
    """Safely extract the first inbound WhatsApp message."""
    try:
        return body["entry"][0]["changes"][0]["value"]["messages"][0]
    except (KeyError, IndexError, TypeError):
        return None


def _extract_text_body(message: Dict) -> Optional[str]:
    if message.get("type") not in {None, "text"}:
        return None

    text = message.get("text")
    if not isinstance(text, dict):
        return None

    body = text.get("body")
    if not isinstance(body, str):
        return None

    return body.strip()


def _unsupported_message_type(message: Dict) -> str:
    message_type = message.get("type") or "message"
    labels = {
        "audio": "voice note",
        "button": "button reply",
        "document": "document",
        "image": "photo",
        "interactive": "interactive message",
        "location": "location",
        "sticker": "sticker",
        "video": "video",
        "voice": "voice note",
    }
    return labels.get(message_type, str(message_type).replace("_", " "))


def _unsupported_message_reply(message: Dict) -> str:
    message_type = _unsupported_message_type(message)
    return conversation_message("unsupported_message", message_type=message_type)


def _main_menu() -> str:
    return conversation_message("main_menu")


def _help_message() -> str:
    return conversation_message("help")


def _direct_rfq_prompt() -> str:
    return conversation_message("direct_rfq_prompt")


def _featured_offers_message(currency: str) -> str:
    offers = get_featured_catalog(limit=4)
    if not offers:
        return conversation_message("no_featured_offers")

    lines = [conversation_message("featured_header")]
    for index, offer in enumerate(offers, start=1):
        starting_price = offer.get("starting_price")
        price_text = (
            f"From {format_price(starting_price, currency)} per {buyer_uom(offer.get('uom'))}"
            if starting_price is not None
            else PRICE_ON_QUOTATION
        )
        lead_time_days = offer.get("lead_time_days")
        lead_time = f"{lead_time_days} days" if lead_time_days else "confirmed in quotation"
        # Never show supplier names or exact stock quantities to buyers.
        lines.append(conversation_message(
            "featured_offer",
            index=index,
            product_name=offer["product_name"],
            brand=offer.get("brand") or "Generic",
            price_text=price_text,
            lead_time=lead_time,
        ))

    lines.append(conversation_message("featured_footer"))
    return "\n\n".join(lines)


def _browse_categories_message(categories: list[str]) -> str:
    if not categories:
        return conversation_message("no_categories")

    lines = [conversation_message("categories_header")]
    for index, category in enumerate(categories, start=1):
        lines.append(f"{index}. {category.title()}")

    lines.append(conversation_message("categories_footer"))
    return "\n".join(lines)


def _subcategory_page(
    category_name: str,
    subcategories: list[str],
    page: int = 0,
) -> tuple[str, list[str], int]:
    max_page = max(0, (len(subcategories) - 1) // SUBCATEGORY_PAGE_SIZE)
    page = min(max(page, 0), max_page)
    start = page * SUBCATEGORY_PAGE_SIZE
    displayed = subcategories[start:start + SUBCATEGORY_PAGE_SIZE]
    lines = [
        conversation_message(
            "category_subcategories_header",
            category_name=category_name.title(),
        )
    ]
    for index, subcategory in enumerate(displayed, start=1):
        lines.append(f"{index}. {subcategory}")

    navigation = []
    if page < max_page:
        navigation.append("NEXT for more")
    if page > 0:
        navigation.append("PREV to go back")
    lines.extend(
        [
            "",
            conversation_message(
                "category_subcategories_footer",
                navigation=" | ".join(navigation),
            ).strip(),
        ]
    )
    return "\n".join(lines), displayed, page


def _family_key(product: Dict) -> str:
    return str(product.get("product_family_id") or product.get("product_id") or "").strip()


def _humanize_family_id(family_id: str) -> str:
    value = re.sub(r"-[A-F0-9]{6}$", "", family_id.upper())
    value = re.sub(r"^(?:FAM-)?(?:SUB-|AUTO-)?", "", value)
    words = value.replace("INSTR", "INSTRUMENTS").replace("CATH", "CATHETERS").split("-")
    return " ".join(words).title()


def _parent_product_name(products: list[Dict]) -> str:
    first = products[0]
    explicit_name = str(first.get("product_family_name") or "").strip()
    if explicit_name:
        return explicit_name
    family_id = _family_key(first)
    known_name = FAMILY_DISPLAY_NAMES.get(family_id.upper())
    if known_name:
        return known_name
    if family_id and family_id != str(first.get("product_id") or ""):
        return _humanize_family_id(family_id)
    return str(first.get("name") or "Product").strip()


def _prices_for_results(results: list[Dict]) -> list[int]:
    prices = []
    for result in results:
        tiers = result.get("pricing") or []
        if tiers:
            prices.extend(tier["unit_price"] for tier in tiers if tier.get("unit_price") is not None)
        elif result.get("default_price") is not None:
            prices.append(result["default_price"])
    return prices


def _offer_price_ranges(results: list[Dict], currency: str) -> str:
    buckets = {}
    for result in results:
        uom = buyer_uom(result.get("uom"))
        for tier in result.get("pricing") or [{"unit_price": result.get("default_price")}]:
            if tier.get("unit_price") is not None:
                key = (tier.get("currency") or result.get("currency") or currency, uom)
                buckets.setdefault(key, []).append(tier["unit_price"])
    return "\n".join(
        f"{format_price_range(min(prices), max(prices), code)} / {uom}"
        for (code, uom), prices in sorted(buckets.items())
    ) or PRICE_ON_QUOTATION


def _build_product_groups(products: list[Dict], data: Dict, currency: str) -> list[Dict]:
    grouped: dict[str, list[Dict]] = {}
    for product in products:
        grouped.setdefault(_family_key(product), []).append(product)

    groups = []
    for family_key, members in grouped.items():
        offer_count = 0
        family_results = []
        stock_qty = 0
        for product in members:
            results = get_results(product["product_id"], data, currency=currency)
            offer_count += len(results)
            family_results.extend(results)
            stock_qty += sum(max(0, result.get("stock_qty") or 0) for result in results)
        price_text = _offer_price_ranges(family_results, currency)
        groups.append(
            {
                "family_key": family_key,
                "display_name": _parent_product_name(members),
                "product_ids": [product["product_id"] for product in members],
                "variant_count": len(members),
                "offer_count": offer_count,
                "price_text": price_text,
                "stock_qty": stock_qty,
            }
        )

    curation = {row.get("family_id") or row.get("product_family_id"): row for row in data.get("parent_products", [])}
    for group in groups:
        row = curation.get(group["family_key"], {})
        group["curation_order"] = (not bool(row), row.get("page") or 0, row.get("position") or 0)
    return sorted(
        groups,
        key=lambda group: (
            *group["curation_order"],
            group["offer_count"] == 0,
            -group["offer_count"],
            -group["stock_qty"],
            group["display_name"].casefold(),
        ),
    )


def _enrich_search_matches(matches: list[Dict], data: Dict, currency: str) -> list[Dict]:
    products = [product for product in data.get("products", []) if product.get("active", True)]
    enriched = []
    for match in matches:
        family_key = _family_key(match)
        family_products = [product for product in products if _family_key(product) == family_key]
        group = _build_product_groups(family_products or [match], data, currency)[0]
        enriched.append(
            {
                **match,
                "search_display_name": group["display_name"],
                "family_product_ids": group["product_ids"],
                "price_text": group["price_text"],
                "offer_count": group["offer_count"],
                "variant_count": group["variant_count"],
            }
        )
    return enriched


def _category_products_message(
    category_name: str,
    product_groups: list[Dict],
    subcategory_name: str | None = None,
    display_limit: int = PRODUCT_DISPLAY_LIMIT,
) -> str:
    if not product_groups:
        return conversation_message("category_empty", category_name=category_name.title())

    display_groups = product_groups[:display_limit]
    heading = subcategory_name or category_name.title()
    lines = [conversation_message("category_products_header", category_name=heading)]
    for index, group in enumerate(display_groups, start=1):
        lines.append(
            conversation_message(
                "category_product_group",
                index=index,
                product_name=group["display_name"],
                price_text=group["price_text"],
                variant_count=group["variant_count"],
                offer_count=group["offer_count"],
            )
        )

    if len(product_groups) > display_limit:
        lines.append("")
        lines.append(conversation_message("category_products_overflow"))

    lines.append("")
    lines.append(conversation_message("category_products_footer"))
    return "\n".join(lines)


def _variant_label(product: Dict, data: Dict) -> str:
    attributes = [
        row
        for row in data.get("product_attributes", [])
        if row.get("product_id") == product.get("product_id")
    ]
    if attributes:
        attribute_priority = {
            "size": 0,
            "gauge": 1,
            "needle_profile": 2,
            "needle_type": 2,
            "lumen": 3,
            "lumens": 3,
            "material": 4,
            "length": 5,
        }
        attributes.sort(
            key=lambda row: (
                attribute_priority.get(str(row.get("attribute_code") or "").casefold(), 99),
                str(row.get("attribute_code") or "").casefold(),
            )
        )
        return ", ".join(
            f"{str(row.get('value')).strip()}{(' ' + str(row.get('unit')).strip()) if row.get('unit') else ''}"
            for row in attributes
            if row.get("value") not in (None, "")
        )

    inventory = data.get("inventory_by_product", {}).get(product.get("product_id"), [])
    sku = inventory[0].get("sku") if inventory else None
    return f"{product.get('name', 'Variant')} · SKU {sku}" if sku else str(product.get("name") or "Variant")


def _build_variant_options(products: list[Dict], data: Dict, currency: str) -> list[Dict]:
    options = []
    for product in products:
        results = get_results(product["product_id"], data, currency=currency)
        options.append(
            {
                **product,
                "variant_label": _variant_label(product, data),
                "price_text": _offer_price_ranges(results, currency),
                "offer_count": len(results),
            }
        )
    return sorted(
        options,
        key=lambda option: (
            option["offer_count"] == 0,
            option["variant_label"].casefold(),
        ),
    )


def _family_variants_message(parent_name: str, variants: list[Dict]) -> str:
    lines = [conversation_message("family_variants_header", product_name=parent_name)]
    for index, variant in enumerate(variants[:PRODUCT_DISPLAY_LIMIT], start=1):
        lines.append(
            conversation_message(
                "family_variant",
                index=index,
                variant_name=variant["variant_label"],
                price_text=variant["price_text"],
                offer_count=variant["offer_count"],
            )
        )
    if len(variants) > PRODUCT_DISPLAY_LIMIT:
        lines.extend(["", conversation_message("family_variants_overflow")])
    lines.extend(["", conversation_message("family_variants_footer")])
    return "\n".join(lines)


def _append_related_products(reply: str, product: Dict, currency: str) -> tuple[str, list[Dict]]:
    try:
        related_products = get_related_catalog(product.get("product_id", ""), limit=3, currency=currency)
    except Exception as exc:
        logger.warning("related_products_unavailable product_id=%s error=%s", product.get("product_id"), exc)
        return reply, []
    if not related_products:
        return reply, []

    lines = [reply, "", conversation_message("related_header")]
    for index, related in enumerate(related_products, start=1):
        price = related.get("starting_price")
        price_text = format_price(price, currency) if price is not None else PRICE_ON_QUOTATION
        lines.append(conversation_message(
            "related_offer",
            index=index,
            product_name=related["product_name"],
            price_text=price_text,
            uom=buyer_uom(related.get("uom")),
        ))
    lines.append(conversation_message("related_footer"))
    return "\n".join(lines), related_products


def is_end_command(text: str) -> bool:
    """Recognize explicit session-close requests without using Twilio's STOP keyword."""
    normalized = re.sub(r"\s+", " ", text.strip().casefold())
    return normalized in END_COMMANDS


def _resolve_category_selection(text: str, categories: list[str]) -> Optional[str]:
    if text.isdigit():
        index = int(text) - 1
        if 0 <= index < len(categories):
            return categories[index]
        return None

    normalized_text = text.strip().lower()
    exact_matches = [category for category in categories if category.lower() == normalized_text]
    if exact_matches:
        return exact_matches[0]

    partial_matches = [category for category in categories if normalized_text in category.lower()]
    if len(partial_matches) == 1:
        return partial_matches[0]

    scored = sorted(
        ((fuzz.WRatio(normalized_text, category.lower()), category) for category in categories),
        key=lambda pair: -pair[0],
    )
    if scored and scored[0][0] >= FUZZY_SELECTION_THRESHOLD:
        if len(scored) == 1 or scored[0][0] - scored[1][0] >= FUZZY_SELECTION_MARGIN:
            return scored[0][1]

    return None


def _resolve_subcategory_selection(
    text: str,
    subcategories: list[str],
    displayed_subcategories: list[str],
) -> Optional[str]:
    if text.isdigit():
        index = int(text) - 1
        return displayed_subcategories[index] if 0 <= index < len(displayed_subcategories) else None

    return _resolve_category_selection(text, subcategories)


def _resolve_category_product_selection(
    text: str,
    category_name: str,
    displayed_products: list[Dict],
    subcategory_name: str | None = None,
) -> Optional[Dict]:
    if text.isdigit():
        index = int(text) - 1
        if 0 <= index < len(displayed_products):
            return displayed_products[index]
        return None

    normalized_text = text.strip().lower()
    category_products = (
        get_products_by_category(category_name, subcategory_name)
        if subcategory_name
        else get_products_by_category(category_name)
    )

    displayed_matches = [
        product
        for product in displayed_products
        if str(product.get("display_name") or product.get("name") or "").casefold() == normalized_text
    ]
    if len(displayed_matches) == 1:
        return displayed_matches[0]

    exact_matches = [product for product in category_products if product["name"].lower() == normalized_text]
    if len(exact_matches) == 1:
        return exact_matches[0]

    partial_matches = [product for product in category_products if normalized_text in product["name"].lower()]
    if len(partial_matches) == 1:
        return partial_matches[0]

    scored = sorted(
        ((fuzz.WRatio(normalized_text, product["name"].lower()), product) for product in category_products),
        key=lambda pair: -pair[0],
    )
    if scored and scored[0][0] >= FUZZY_SELECTION_THRESHOLD:
        if len(scored) == 1 or scored[0][0] - scored[1][0] >= FUZZY_SELECTION_MARGIN:
            return scored[0][1]

    return None


def _resolve_variant_selection(text: str, displayed_variants: list[Dict]) -> Optional[Dict]:
    if text.isdigit():
        index = int(text) - 1
        displayed_count = min(len(displayed_variants), PRODUCT_DISPLAY_LIMIT)
        return displayed_variants[index] if 0 <= index < displayed_count else None

    normalized_text = text.strip().casefold()
    exact = [
        variant
        for variant in displayed_variants
        if normalized_text
        in {
            str(variant.get("name") or "").casefold(),
            str(variant.get("variant_label") or "").casefold(),
        }
    ]
    if len(exact) == 1:
        return exact[0]

    partial = [
        variant
        for variant in displayed_variants
        if normalized_text
        and normalized_text in str(variant.get("variant_label") or "").casefold()
    ]
    if len(partial) == 1:
        return partial[0]

    scored = sorted(
        (
            (
                fuzz.WRatio(normalized_text, str(variant.get("variant_label") or "").casefold()),
                variant,
            )
            for variant in displayed_variants
        ),
        key=lambda pair: -pair[0],
    )
    if scored and scored[0][0] >= FUZZY_SELECTION_THRESHOLD:
        if len(scored) == 1 or scored[0][0] - scored[1][0] >= FUZZY_SELECTION_MARGIN:
            return scored[0][1]
    return None


def _split_pipe_message(text: str) -> list[str]:
    return [part.strip() for part in text.split("|") if part.strip()]


def _parse_buyer_intro(text: str, sender: str) -> tuple[str, str, str]:
    parts = _split_pipe_message(text)
    buyer_name = parts[0] if parts else sender
    organization = parts[1] if len(parts) > 1 else "WhatsApp buyer"
    need = parts[2] if len(parts) > 2 else text.strip()
    return buyer_name, organization, need


def _parse_buyer_facility_details(text: str) -> tuple[str, str, str]:
    """Parse contact name, organization, and delivery location from a reply."""
    parts = [part.strip() for part in re.split(r"\n|,", text) if part.strip()]
    if not parts:
        return "", "", ""
    if len(parts) == 1:
        return parts[0], "", ""
    if len(parts) == 2:
        return parts[0], parts[1], ""
    return parts[0], parts[1], ", ".join(parts[2:])


def _load_buyer_profile(sender: str) -> Optional[Dict]:
    db = SessionLocal()
    try:
        profile = get_buyer_profile(db, sender)
        if not profile:
            return None
        return {
            "contact_name": profile.contact_name,
            "organization": profile.organization,
            "delivery_location": profile.delivery_location,
            "country": profile.country,
            "preferred_currency": profile.preferred_currency,
        }
    except Exception as exc:
        logger.warning("buyer_profile_unavailable sender=%s error=%s", sender, exc)
        return None
    finally:
        db.close()


def _log_user_input(sender: str, state: str, text: str) -> None:
    logger.info("whatsapp_input sender=%s state=%s text=%s", sender, state, text[:200])


def _transition_session(sender: str, current_state: str, next_state: ConversationState, **payload) -> None:
    logger.info("state_transition sender=%s from=%s to=%s", sender, current_state, next_state.value)
    session_payload = {"state": next_state.value}
    session_payload.update(payload)
    save_session(sender, session_payload)


async def _create_whatsapp_rfq(
    sender: str,
    buyer_name: str,
    product_name: str,
    quantity: int,
    organization: str,
    delivery_location: str,
    source: str,
    product_id: Optional[str] = None,
    vendor_id: Optional[str] = None,
    vendor_name: Optional[str] = None,
    vendor_phone: Optional[str] = None,
    notes: Optional[str] = None,
    currency: str = "UGX",
    equipment_review_required: bool = False,
    manual_review_reason: Optional[str] = None,
    items: Optional[list[dict]] = None,
) -> tuple[int, bool]:
    db = SessionLocal()
    try:
        rfq = create_rfq_request(
            db,
            RFQCreate(
                items=items,
                buyer_name=buyer_name,
                organization=organization,
                phone=sender,
                product_id=product_id,
                product_name=product_name,
                vendor_id=vendor_id,
                vendor_name=vendor_name,
                vendor_phone=vendor_phone,
                quantity=quantity,
                delivery_location=delivery_location,
                notes=notes,
                currency=currency,
                source=source,
                procurement_stage="formal_purchase",
                formal_quote=True,
                equipment_review_required=equipment_review_required,
                manual_review_reason=manual_review_reason,
            ),
        )
        supplier_notified = await dispatch_rfq_notifications(rfq, vendor_phone)
    finally:
        db.close()
    return rfq.id, supplier_notified


async def _capture_sales_lead(sender: str, text: str, source: str) -> int:
    buyer_name, organization, need = _parse_buyer_intro(text, sender)
    db = SessionLocal()
    try:
        lead = create_buyer_lead(
            db,
            BuyerLeadCreate(
                buyer_name=buyer_name,
                organization=organization,
                phone=sender,
                use_case=need,
                source=source,
            ),
        )
    finally:
        db.close()

    await dispatch_lead_notification(lead)
    return lead.id


async def handle_incoming_message(message: Dict):
    """Production-ready WhatsApp procurement flow."""
    sender = message.get("from")
    if not sender:
        log_audit_event("unknown", "whatsapp_missing_sender", {"message": message})
        return

    text = _extract_text_body(message)
    if text is None:
        log_audit_event(
            sender,
            "unsupported_whatsapp_message",
            {"message_type": message.get("type", "unknown")},
        )
        await send_whatsapp_message(sender, _unsupported_message_reply(message))
        return

    text_clean = text.lower()
    language = _detect_language(sender, text)
    logger.debug("assumed_language sender=%s language=%s", sender, language)
    currency = get_currency_for_phone(sender)

    session = get_session(sender) or {}
    current_state = session.get("state", ConversationState.MENU.value)
    if not validate_state(current_state):
        logger.warning("invalid_state sender=%s state=%s", sender, current_state)
        current_state = ConversationState.MENU.value
    _log_user_input(sender, current_state, text)

    if is_end_command(text):
        _transition_session(sender, current_state, ConversationState.IDLE, ended_by="buyer")
        log_audit_event(sender, "whatsapp_conversation_ended", {"previous_state": current_state})
        try:
            record_funnel_event(
                "conversation_ended",
                source="whatsapp",
                actor_id=sender,
                data={"previous_state": current_state, "ended_by": "buyer"},
            )
        except Exception as exc:
            logger.warning("conversation_end_event_failed sender=%s error=%s", sender, exc)
        await send_whatsapp_message(sender, conversation_message("conversation_closed"))
        return

    if not validate_whatsapp_message(text):
        await send_whatsapp_message(sender, conversation_message("message_too_long"))
        return

    if text_clean in ["0", "m", "menu", "back"]:
        await send_whatsapp_message(sender, _main_menu())
        _transition_session(sender, current_state, ConversationState.MENU)
        return

    if text_clean in {"search", "categories", "quote", "sales"} and current_state not in {
        ConversationState.IDLE.value,
        ConversationState.MENU.value,
    }:
        if text_clean == "search":
            await send_whatsapp_message(sender, conversation_message("search_prompt"))
            _transition_session(sender, current_state, ConversationState.SEARCHING)
        elif text_clean == "categories":
            categories = get_categories()
            await send_whatsapp_message(sender, _browse_categories_message(categories))
            _transition_session(
                sender,
                current_state,
                ConversationState.BROWSING_CATEGORIES,
                categories=categories,
            )
        elif text_clean == "quote":
            await send_whatsapp_message(sender, _direct_rfq_prompt())
            _transition_session(sender, current_state, ConversationState.DIRECT_RFQ, formal_purchase=True)
        else:
            await send_whatsapp_message(sender, conversation_message("sales_prompt_short"))
            _transition_session(sender, current_state, ConversationState.TALK_TO_AGENT)
        return

    if not session or current_state in {ConversationState.IDLE.value, ConversationState.MENU.value}:
        data = get_cached_data()
        if '|' in text or len(parse_requested_items_safe(text, data)) > 1:
            await _collect_requested_rfq(sender, text, {"buyer_profile": _load_buyer_profile(sender)}, currency)
            return
        entry_intent = classify_entry_intent(
            text,
            data.get("products", []),
            data.get("aliases", []),
            get_categories(),
            data=data,
        )

        if entry_intent.intent == BuyerIntent.RESTRICTED_MEDICINE:
            await send_whatsapp_message(sender, conversation_message("restricted_medicine"))
            _transition_session(sender, current_state, ConversationState.MENU)
            return

        if entry_intent.intent == BuyerIntent.GREETING or (
            entry_intent.intent == BuyerIntent.NAVIGATION and entry_intent.navigation == "menu"
        ):
            profile = _load_buyer_profile(sender)
            greeting = _main_menu()
            if profile:
                first_name = profile["contact_name"].split()[0]
                greeting = conversation_message("returning_greeting", first_name=first_name, menu=greeting)
            await send_whatsapp_message(sender, greeting)
            _transition_session(sender, current_state, ConversationState.MENU)
            return

        if entry_intent.intent == BuyerIntent.SALES or (
            entry_intent.intent == BuyerIntent.NAVIGATION and entry_intent.navigation == "sales"
        ):
            await send_whatsapp_message(sender, conversation_message("sales_prompt"))
            _transition_session(sender, current_state, ConversationState.TALK_TO_AGENT)
            return

        if entry_intent.intent in {BuyerIntent.FORMAL_PURCHASE, BuyerIntent.MULTI_ITEM} or (
            entry_intent.intent == BuyerIntent.NAVIGATION and entry_intent.navigation == "quote"
        ):
            if entry_intent.intent in {BuyerIntent.FORMAL_PURCHASE, BuyerIntent.MULTI_ITEM}:
                await _collect_requested_rfq(sender, text, {"buyer_profile": _load_buyer_profile(sender)}, currency)
                return
            profile = _load_buyer_profile(sender)
            prompt = _direct_rfq_prompt()
            if profile and profile.get("delivery_location"):
                prompt = conversation_message(
                    "returning_rfq",
                    first_name=profile["contact_name"].split()[0],
                    organization=profile["organization"],
                    delivery_location=profile["delivery_location"],
                    prompt=prompt,
                )
            await send_whatsapp_message(sender, prompt)
            _transition_session(
                sender,
                current_state,
                ConversationState.DIRECT_RFQ,
                formal_purchase=True,
                buyer_profile=profile,
            )
            return

        if entry_intent.intent == BuyerIntent.CATEGORY:
            subcategories = get_subcategories_by_category(entry_intent.category)
            if len(subcategories) > 1 or (subcategories and has_browse_menu()):
                message, displayed_subcategories, page = _subcategory_page(
                    entry_intent.category,
                    subcategories,
                )
                await send_whatsapp_message(sender, message)
                _transition_session(
                    sender,
                    current_state,
                    ConversationState.BROWSING_SUBCATEGORIES,
                    category_name=entry_intent.category,
                    subcategories=subcategories,
                    displayed_subcategories=displayed_subcategories,
                    subcategory_page=page,
                )
            else:
                data = get_cached_data()
                category_products = get_products_by_category(entry_intent.category)
                product_groups = _build_product_groups(category_products, data, currency)
                await send_whatsapp_message(
                    sender,
                    _category_products_message(entry_intent.category, product_groups),
                )
                _transition_session(
                    sender,
                    current_state,
                    ConversationState.CATEGORY_SELECTED,
                    category_name=entry_intent.category,
                    category_products=product_groups[:PRODUCT_DISPLAY_LIMIT],
                )
            return

        if entry_intent.intent == BuyerIntent.NAVIGATION and entry_intent.navigation == "categories":
            categories = get_categories()
            await send_whatsapp_message(sender, _browse_categories_message(categories))
            _transition_session(
                sender,
                current_state,
                ConversationState.BROWSING_CATEGORIES,
                categories=categories,
            )
            return

        if entry_intent.intent in {BuyerIntent.PRODUCT, BuyerIntent.PRODUCT_WITH_QUANTITY}:
            current_state = ConversationState.SEARCHING.value
            session = {
                "state": current_state,
                "pending_quantity": entry_intent.quantity,
                "pending_uom": entry_intent.uom,
            }
        elif entry_intent.intent == BuyerIntent.NAVIGATION and entry_intent.navigation == "search":
            await send_whatsapp_message(sender, conversation_message("search_prompt"))
            _transition_session(sender, current_state, ConversationState.SEARCHING)
            return
        else:
            await send_whatsapp_message(sender, conversation_message("entry_fallback"))
            _transition_session(sender, current_state, ConversationState.MENU)
            return

    if current_state == ConversationState.SEARCHING.value:
        if is_bulk_request(text):
            await _collect_requested_rfq(sender, text, {"buyer_profile": _load_buyer_profile(sender)}, currency)
            return

        if not validate_product_query(text):
            await send_whatsapp_message(sender, conversation_message("search_invalid"))
            return

        data = get_cached_data()
        product_matches = find_products(
            text,
            data.get("products", []),
            data.get("aliases", []),
            limit=PRODUCT_DISPLAY_LIMIT,
            data=data,
        )
        product_matches = _enrich_search_matches(product_matches, data, currency)
        record_funnel_event(
            "search",
            source="whatsapp",
            actor_id=sender,
            data={"query": text, "match_count": len(product_matches)},
        )
        if len(product_matches) > 1:
            record_funnel_event(
                "results",
                source="whatsapp",
                actor_id=sender,
                data={
                    "query": text,
                    "result_count": len(product_matches),
                    "product_ids": [product["product_id"] for product in product_matches],
                    "requires_disambiguation": True,
                },
            )
            await send_whatsapp_message(sender, format_ambiguous_match_message(product_matches))
            _transition_session(
                sender,
                current_state,
                ConversationState.SEARCH_DISAMBIGUATION,
                search_matches=product_matches,
            )
            return

        product = product_matches[0] if product_matches else None
        if not product:
            record_funnel_event(
                "results",
                source="whatsapp",
                actor_id=sender,
                data={"query": text, "result_count": 0, "requires_disambiguation": False},
            )
            await send_whatsapp_message(sender, conversation_message("search_no_match"))
            _transition_session(sender, current_state, ConversationState.SEARCHING)
            return

        family_product_ids = product.get("family_product_ids", [])
        if len(family_product_ids) > 1:
            products_by_id = data.get("products_by_id") or {
                candidate["product_id"]: candidate for candidate in data.get("products", [])
            }
            family_products = [
                products_by_id[product_id]
                for product_id in family_product_ids
                if product_id in products_by_id
            ]
            variants = _build_variant_options(family_products, data, currency)
            await send_whatsapp_message(
                sender,
                _family_variants_message(product["search_display_name"], variants),
            )
            _transition_session(
                sender,
                current_state,
                ConversationState.FAMILY_SELECTED,
                family_name=product["search_display_name"],
                family_variants=variants,
            )
            return

        results = get_results(product["product_id"], data, currency=currency)
        record_funnel_event(
            "results",
            source="whatsapp",
            actor_id=sender,
            data={
                "query": text,
                "result_count": len(results),
                "product_ids": [product["product_id"]],
                "requires_disambiguation": False,
            },
        )
        if not results:
            await send_whatsapp_message(sender, conversation_message("search_no_live_offer_menu"))
            _transition_session(sender, current_state, ConversationState.MENU)
            return

        reply, option_map = format_results(product["name"], results, currency=currency)
        pending_quantity = session.get("pending_quantity")
        if pending_quantity:
            reply = conversation_message(
                "requested_quantity",
                quantity=pending_quantity,
                uom=session.get("pending_uom") or "units",
                results=reply,
            )
        reply, related_products = _append_related_products(reply, product, currency)
        _transition_session(
            sender,
            current_state,
            ConversationState.VIEWING_RESULTS,
            product=product,
            options=option_map,
            related_products=related_products,
        )
        await send_whatsapp_message(sender, reply)
        return

    if current_state == ConversationState.SEARCH_DISAMBIGUATION.value:
        search_matches = session.get("search_matches", [])
        if text_clean in {"rfq", "quote", "quotation"}:
            await send_whatsapp_message(sender, _direct_rfq_prompt())
            _transition_session(sender, current_state, ConversationState.DIRECT_RFQ)
            return
        if text_clean in {"agent", "sales", "help"}:
            await send_whatsapp_message(sender, conversation_message("sales_handoff_prompt"))
            _transition_session(sender, current_state, ConversationState.TALK_TO_AGENT)
            return

        try:
            selected_index = int(text_clean) - 1
        except ValueError:
            selected_index = -1

        if selected_index < 0 or selected_index >= len(search_matches):
            await send_whatsapp_message(sender, conversation_message("disambiguation_invalid"))
            return

        selected_product = search_matches[selected_index]
        data = get_cached_data()
        family_product_ids = selected_product.get("family_product_ids", [])
        if len(family_product_ids) > 1:
            products_by_id = data.get("products_by_id") or {
                candidate["product_id"]: candidate for candidate in data.get("products", [])
            }
            family_products = [
                products_by_id[product_id]
                for product_id in family_product_ids
                if product_id in products_by_id
            ]
            variants = _build_variant_options(family_products, data, currency)
            await send_whatsapp_message(
                sender,
                _family_variants_message(selected_product["search_display_name"], variants),
            )
            _transition_session(
                sender,
                current_state,
                ConversationState.FAMILY_SELECTED,
                family_name=selected_product["search_display_name"],
                family_variants=variants,
            )
            return

        results = get_results(selected_product["product_id"], data, currency=currency)
        record_funnel_event(
            "results",
            source="whatsapp",
            actor_id=sender,
            data={
                "result_count": len(results),
                "product_ids": [selected_product["product_id"]],
                "requires_disambiguation": False,
                "disambiguated": True,
            },
        )
        if not results:
            await send_whatsapp_message(sender, conversation_message("search_no_live_offer_rfq"))
            return

        reply, option_map = format_results(selected_product["name"], results, currency=currency)
        reply, related_products = _append_related_products(reply, selected_product, currency)
        _transition_session(
            sender,
            current_state,
            ConversationState.VIEWING_RESULTS,
            product=selected_product,
            options=option_map,
            related_products=related_products,
        )
        await send_whatsapp_message(sender, reply)
        return

    if current_state == ConversationState.BROWSING_CATEGORIES.value:
        categories = session.get("categories") or get_categories()
        selected_category = _resolve_category_selection(text_clean, categories)
        if not selected_category:
            await send_whatsapp_message(sender, conversation_message("category_invalid"))
            return

        subcategories = get_subcategories_by_category(selected_category)
        record_funnel_event(
            "results",
            source="whatsapp",
            actor_id=sender,
            data={
                "channel": "category_browse",
                "category": selected_category,
                "result_count": len(get_products_by_category(selected_category)),
            },
        )
        if len(subcategories) > 1 or (subcategories and has_browse_menu()):
            message, displayed_subcategories, page = _subcategory_page(
                selected_category,
                subcategories,
            )
            await send_whatsapp_message(sender, message)
            _transition_session(
                sender,
                current_state,
                ConversationState.BROWSING_SUBCATEGORIES,
                category_name=selected_category,
                subcategories=subcategories,
                displayed_subcategories=displayed_subcategories,
                subcategory_page=page,
            )
        else:
            data = get_cached_data()
            category_products = get_products_by_category(selected_category)
            product_groups = _build_product_groups(category_products, data, currency)
            await send_whatsapp_message(
                sender,
                _category_products_message(selected_category, product_groups),
            )
            _transition_session(
                sender,
                current_state,
                ConversationState.CATEGORY_SELECTED,
                category_name=selected_category,
                category_products=product_groups[:PRODUCT_DISPLAY_LIMIT],
            )
        return

    if current_state == ConversationState.BROWSING_SUBCATEGORIES.value:
        category_name = session.get("category_name", "")
        subcategories = session.get("subcategories") or get_subcategories_by_category(category_name)
        page = session.get("subcategory_page", 0)
        if text_clean in {"next", "more"}:
            message, displayed_subcategories, page = _subcategory_page(
                category_name,
                subcategories,
                page + 1,
            )
            await send_whatsapp_message(sender, message)
            _transition_session(
                sender,
                current_state,
                ConversationState.BROWSING_SUBCATEGORIES,
                category_name=category_name,
                subcategories=subcategories,
                displayed_subcategories=displayed_subcategories,
                subcategory_page=page,
            )
            return
        if text_clean in {"prev", "previous"}:
            message, displayed_subcategories, page = _subcategory_page(
                category_name,
                subcategories,
                page - 1,
            )
            await send_whatsapp_message(sender, message)
            _transition_session(
                sender,
                current_state,
                ConversationState.BROWSING_SUBCATEGORIES,
                category_name=category_name,
                subcategories=subcategories,
                displayed_subcategories=displayed_subcategories,
                subcategory_page=page,
            )
            return

        displayed_subcategories = session.get("displayed_subcategories", [])
        selected_subcategory = _resolve_subcategory_selection(
            text_clean,
            subcategories,
            displayed_subcategories,
        )
        if not selected_subcategory:
            await send_whatsapp_message(sender, conversation_message("subcategory_invalid"))
            return

        data = get_cached_data()
        products = get_products_by_category(category_name, selected_subcategory)
        product_groups = _build_product_groups(products, data, currency)
        await send_whatsapp_message(
            sender,
            _category_products_message(
                category_name,
                product_groups,
                subcategory_name=selected_subcategory,
            ),
        )
        _transition_session(
            sender,
            current_state,
            ConversationState.CATEGORY_SELECTED,
            category_name=category_name,
            subcategory_name=selected_subcategory,
            category_products=product_groups[:PRODUCT_DISPLAY_LIMIT],
        )
        return

    if current_state == ConversationState.CATEGORY_SELECTED.value:
        category_name = session.get("category_name", "")
        subcategory_name = session.get("subcategory_name")
        displayed_products = session.get("category_products", [])
        selected_group = _resolve_category_product_selection(
            text,
            category_name,
            displayed_products,
            subcategory_name,
        )
        if not selected_group:
            await send_whatsapp_message(sender, conversation_message("category_product_invalid"))
            return

        data = get_cached_data()
        if selected_group.get("product_ids"):
            products_by_id = data.get("products_by_id") or {
                product["product_id"]: product for product in data.get("products", [])
            }
            family_products = [
                products_by_id[product_id]
                for product_id in selected_group["product_ids"]
                if product_id in products_by_id
            ]
        else:
            family_products = [selected_group]

        if len(family_products) > 1:
            variants = _build_variant_options(family_products, data, currency)
            await send_whatsapp_message(
                sender,
                _family_variants_message(selected_group.get("display_name") or family_products[0]["name"], variants),
            )
            _transition_session(
                sender,
                current_state,
                ConversationState.FAMILY_SELECTED,
                family_name=selected_group.get("display_name") or family_products[0]["name"],
                family_variants=variants,
            )
            return

        selected_product = family_products[0]
        results = get_results(selected_product["product_id"], data, currency=currency)
        record_funnel_event(
            "results",
            source="whatsapp",
            actor_id=sender,
            data={
                "channel": "category_browse",
                "product_id": selected_product["product_id"],
                "result_count": len(results),
            },
        )
        if not results:
            await send_whatsapp_message(sender, conversation_message("category_no_live_offer"))
            return

        reply, option_map = format_results(selected_product["name"], results, currency=currency)
        reply, related_products = _append_related_products(reply, selected_product, currency)
        _transition_session(
            sender,
            current_state,
            ConversationState.VIEWING_RESULTS,
            product=selected_product,
            options=option_map,
            related_products=related_products,
        )
        await send_whatsapp_message(sender, reply)
        return

    if current_state == ConversationState.FAMILY_SELECTED.value:
        variants = session.get("family_variants", [])
        selected_product = _resolve_variant_selection(text, variants)
        if not selected_product:
            await send_whatsapp_message(sender, conversation_message("family_variant_invalid"))
            return

        data = get_cached_data()
        results = get_results(selected_product["product_id"], data, currency=currency)
        record_funnel_event(
            "results",
            source="whatsapp",
            actor_id=sender,
            data={
                "channel": "family_browse",
                "product_id": selected_product["product_id"],
                "result_count": len(results),
            },
        )
        if not results:
            await send_whatsapp_message(sender, conversation_message("category_no_live_offer"))
            return

        reply, option_map = format_results(selected_product["name"], results, currency=currency)
        reply, related_products = _append_related_products(reply, selected_product, currency)
        _transition_session(
            sender,
            current_state,
            ConversationState.VIEWING_RESULTS,
            product=selected_product,
            options=option_map,
            related_products=related_products,
        )
        await send_whatsapp_message(sender, reply)
        return

    if current_state == ConversationState.VIEWING_RESULTS.value:
        related_match = re.fullmatch(r"r(\d+)", text_clean)
        if related_match:
            related_products = session.get("related_products", [])
            related_index = int(related_match.group(1)) - 1
            if related_index < 0 or related_index >= len(related_products):
                await send_whatsapp_message(sender, conversation_message("related_invalid"))
                return

            selected_related = related_products[related_index]
            data = get_cached_data()
            products_by_id = data.get("products_by_id") or {
                product["product_id"]: product for product in data.get("products", [])
            }
            selected_product = products_by_id.get(selected_related.get("product_id"))
            if not selected_product:
                await send_whatsapp_message(sender, conversation_message("related_missing"))
                return

            results = get_results(selected_product["product_id"], data, currency=currency)
            record_funnel_event(
                "cross_sell_click",
                source="whatsapp",
                actor_id=sender,
                data={
                    "from_product_id": session.get("product", {}).get("product_id"),
                    "to_product_id": selected_product["product_id"],
                    "position": related_index + 1,
                },
            )
            if not results:
                await send_whatsapp_message(sender, conversation_message("related_no_live_offer"))
                return

            reply, option_map = format_results(selected_product["name"], results, currency=currency)
            reply, next_related_products = _append_related_products(reply, selected_product, currency)
            _transition_session(
                sender,
                current_state,
                ConversationState.VIEWING_RESULTS,
                product=selected_product,
                options=option_map,
                related_products=next_related_products,
            )
            await send_whatsapp_message(sender, reply)
            return

        try:
            option_num = int(text_clean)
        except ValueError:
            await send_whatsapp_message(sender, conversation_message("offer_number_prompt"))
            return

        options = session.get("options", [])
        if 1 <= option_num <= len(options):
            selected = options[option_num - 1]
            sku_line = f"SKU: {selected.get('sku')}\n" if selected.get("sku") else ""
            _transition_session(
                sender,
                current_state,
                ConversationState.SELECTING_PRODUCT,
                product=session.get("product"),
                options=options,
                selected_item=selected,
            )
            await send_whatsapp_message(
                sender,
                conversation_message(
                    "offer_selected",
                    brand=selected.get("brand") or "Option 1",
                    sku_line=sku_line,
                    uom=buyer_uom(selected.get("uom")),
                    min_qty=selected.get("min_qty", 1),
                ),
            )
            return

        await send_whatsapp_message(sender, conversation_message("offer_invalid"))
        return

    if current_state == ConversationState.SELECTING_PRODUCT.value:
        try:
            quantity = int(text_clean)
        except ValueError:
            await send_whatsapp_message(sender, conversation_message("quantity_integer"))
            return

        if not validate_quantity(quantity):
            await send_whatsapp_message(sender, conversation_message("quantity_positive"))
            return

        selected = session.get("selected_item", {})
        minimum_quantity = selected.get("min_qty", 1)
        if quantity < minimum_quantity:
            await send_whatsapp_message(
                sender,
                conversation_message(
                    "quantity_below_minimum",
                    minimum_quantity=minimum_quantity,
                    uom=buyer_uom(selected.get("uom")),
                ),
            )
            return

        _transition_session(
            sender,
            current_state,
            ConversationState.VIEWING_PRICE,
            product=session.get("product"),
            options=session.get("options", []),
            selected_item=selected,
            quantity=quantity,
        )
        default_price = selected.get("default_price")
        if default_price is None:
            # Price not verified by the team: never show a number.
            price_message = conversation_message(
                "price_menu_quotation",
                uom=buyer_uom(selected.get("uom")),
            )
        else:
            price_message = conversation_message(
                "price_menu",
                price_text=format_price(default_price, currency),
                uom=buyer_uom(selected.get("uom")),
            )
        await send_whatsapp_message(sender, price_message)
        return

    if current_state == ConversationState.VIEWING_PRICE.value:
        if text_clean == "1":
            await send_whatsapp_message(sender, conversation_message("rfq_contact_prompt"))
            _transition_session(
                sender,
                current_state,
                ConversationState.RFQ_FLOW,
                product=session.get("product"),
                selected_item=session.get("selected_item"),
                quantity=session.get("quantity"),
            )
            return
        if text_clean == "2":
            await send_whatsapp_message(sender, conversation_message("sales_handoff_prompt"))
            _transition_session(
                sender,
                current_state,
                ConversationState.TALK_TO_AGENT,
                selected_item=session.get("selected_item"),
                quantity=session.get("quantity"),
            )
            return
        if text_clean == "3":
            _transition_session(
                sender,
                current_state,
                ConversationState.VIEWING_RESULTS,
                product=session.get("product"),
                options=session.get("options", []),
            )
            await send_whatsapp_message(sender, conversation_message("returning_to_offers"))
            return

        await send_whatsapp_message(sender, conversation_message("price_menu_invalid"))
        return

    if current_state == ConversationState.RFQ_FLOW.value:
        selected = session.get("selected_item", {})
        product = session.get("product", {})
        quantity = session.get("quantity", 1)
        contact_name, organization, delivery_location = _parse_buyer_facility_details(text)

        if (
            not validate_contact_name(contact_name)
            or not validate_facility_name(organization)
            or not validate_delivery_location(delivery_location)
        ):
            await send_whatsapp_message(sender, conversation_message("rfq_contact_prompt"))
            return

        try:
            rfq_id, supplier_notified = await _create_whatsapp_rfq(
                sender=sender,
                buyer_name=contact_name,
                product_name=product.get("name", selected.get("brand", "Medical supply")),
                quantity=quantity,
                organization=organization,
                delivery_location=delivery_location,
                source="whatsapp_selected_offer",
                product_id=product.get("product_id"),
                vendor_id=selected.get("vendor_id"),
                vendor_name=selected.get("vendor_name"),
                vendor_phone=selected.get("vendor_phone"),
                notes=(
                    f"Selected brand: {selected.get('brand') or 'Generic'} | "
                    f"SKU: {selected.get('sku') or 'N/A'} | "
                    f"UoM: {buyer_uom(selected.get('uom'))}"
                ),
                currency=currency,
                equipment_review_required=is_equipment_product(product),
                manual_review_reason=(
                    "equipment_technical_review"
                    if is_equipment_product(product)
                    else None
                ),
            )
        except Exception as exc:
            log_audit_event(sender, "whatsapp_rfq_failed", {"error": str(exc)})
            await send_whatsapp_message(sender, conversation_message("rfq_submit_error"))
            _transition_session(sender, current_state, ConversationState.MENU)
            return

        supplier_text = conversation_message("supplier_notified" if supplier_notified else "supplier_manual")
        await send_whatsapp_message(
            sender,
            conversation_message("rfq_received", rfq_id=rfq_id, routing_message=supplier_text),
        )
        _transition_session(sender, current_state, ConversationState.MENU)
        return

    if current_state == ConversationState.DIRECT_RFQ.value:
        await _collect_requested_rfq(sender, text, session, currency)
        return

    if current_state == ConversationState.TALK_TO_AGENT.value:
        try:
            lead_id = await _capture_sales_lead(sender, text, "whatsapp_sales_handoff")
        except Exception as exc:
            log_audit_event(sender, "sales_lead_failed", {"error": str(exc)})
            await send_whatsapp_message(sender, conversation_message("sales_handoff_error"))
            _transition_session(sender, current_state, ConversationState.MENU)
            return

        await send_whatsapp_message(
            sender,
            conversation_message("sales_handoff_received", lead_id=lead_id),
        )
        _transition_session(sender, current_state, ConversationState.MENU)
        return

    await send_whatsapp_message(sender, conversation_message("unknown_state"))


def parse_requested_items_safe(text, data):
    try:
        return parse_requested_items(text, data.get('products', []))
    except ValueError:
        return [{}] * 21


async def _collect_requested_rfq(sender, text, session, currency):
    data = get_cached_data()
    draft = dict(session.get('request_draft') or {})
    profile = session.get('buyer_profile') or {}
    for field, profile_key in [('buyer_name', 'contact_name'), ('organization', 'organization'), ('delivery_location', 'delivery_location')]:
        if not draft.get(field) and profile.get(profile_key):
            draft[field] = profile[profile_key]
    awaiting = session.get('request_field')
    if awaiting:
        validators = {'buyer_name': validate_contact_name, 'organization': validate_facility_name, 'delivery_location': validate_delivery_location}
        if not validators[awaiting](text):
            await send_whatsapp_message(sender, conversation_message('request_' + awaiting))
            return
        draft[awaiting] = text.strip()
    elif session.get('request_confirm') and text.lower() == 'yes':
        items = resolve_requested_items(draft['items'], data, currency)
        by_id = {p['product_id']: p for p in data.get('products', [])}
        equipment = any(is_equipment_product(by_id.get(i.get('product_id'), {'name': i['product_name']})) for i in items)
        try:
            rfq_id, _ = await _create_whatsapp_rfq(sender=sender, buyer_name=draft['buyer_name'],
                organization=draft['organization'], delivery_location=draft['delivery_location'],
                product_name=items[0]['product_name'], quantity=items[0]['quantity'], items=items,
                source='whatsapp_bulk_rfq' if len(items) > 1 else 'whatsapp_direct_rfq', currency=currency,
                equipment_review_required=equipment, manual_review_reason=session.get('manual_review_reason'),
                notes='Buyer confirmed parsed item quantities')
        except Exception:
            await send_whatsapp_message(sender, conversation_message('direct_rfq_submit_error'))
            return
        _transition_session(sender, ConversationState.DIRECT_RFQ.value, ConversationState.MENU)
        await send_whatsapp_message(sender, conversation_message('direct_rfq_received', rfq_id=rfq_id))
        return
    else:
        item_text = text
        if '|' in text:
            parts = [p.strip() for p in text.split('|')]
            if len(parts) in {4, 5}:
                draft.update(buyer_name=parts[0], organization=parts[-2], delivery_location=parts[-1])
                item_text = parts[1]
                if len(parts) == 5 and len(parse_requested_items_safe(item_text, data)) == 1:
                    item_text += ' x' + parts[2]
            elif len(parts) == 2 and profile:
                item_text = parts[0] + ' x' + parts[1]
            else:
                await send_whatsapp_message(sender, conversation_message('direct_rfq_invalid_format'))
                return
        try:
            draft['items'] = parse_requested_items(item_text, data.get('products', []))
            if not draft['items']:
                raise ValueError()
        except ValueError:
            await send_whatsapp_message(sender, conversation_message('request_item_limit'))
            return
    for field, validator in [('buyer_name', validate_contact_name), ('organization', validate_facility_name), ('delivery_location', validate_delivery_location)]:
        if not validator(draft.get(field, '')):
            _transition_session(sender, ConversationState.DIRECT_RFQ.value, ConversationState.DIRECT_RFQ,
                request_draft=draft, request_field=field, manual_review_reason=session.get('manual_review_reason'))
            await send_whatsapp_message(sender, conversation_message('request_' + field))
            return
    _transition_session(sender, ConversationState.DIRECT_RFQ.value, ConversationState.DIRECT_RFQ,
        request_draft=draft, request_confirm=True, manual_review_reason=session.get('manual_review_reason'))
    lines = [f"{n}. {i['product_name']} x{i['quantity']} {buyer_uom(i.get('uom'))}" +
             ('' if i['quantity_stated'] else ' (quantity not stated)') for n, i in enumerate(draft['items'], 1)]
    # Send every line in bounded messages, without silently truncating a list.
    chunk = ''
    for line in lines:
        if len(chunk) + len(line) > 1200:
            await send_whatsapp_message(sender, chunk)
            chunk = ''
        chunk += line[:1000] + '\n'
    await send_whatsapp_message(sender, chunk + conversation_message('request_confirm'))
