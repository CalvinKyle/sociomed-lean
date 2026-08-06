import logging
import re
from typing import Dict, Optional

from rapidfuzz import fuzz

from app.core.config import (
    ENABLE_CATEGORY_BROWSE,
    ENABLE_FEATURED_OFFERS,
    ENABLE_RELATED_PRODUCTS,
    LAUNCH_MODE,
    SALES_AGENT_PHONE,
)
from app.core.currency import format_price, get_currency_for_phone
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
from app.data_access.catalog import get_categories, get_products_by_category
from app.data_access.funnel import record_funnel_event
from app.models.db import SessionLocal
from app.models.formatter import MAX_VISIBLE_OFFERS, OFFER_OVERFLOW_LINE, OFFER_VALIDITY_DAYS, format_results
from app.schemas.schemas import BuyerLeadCreate, RFQCreate
from app.services.catalog import get_featured_catalog, get_related_catalog
from app.services.procurement import (
    create_buyer_lead,
    create_rfq_request,
    dispatch_lead_notification,
    dispatch_rfq_notifications,
    generate_pfi_for_eligible_rfq,
    handle_operator_pfi_command,
)
from app.services.rfq_triage import (
    format_ambiguous_match_message,
    is_bulk_request,
    is_complex_bulk_request,
    parse_direct_rfq_message,
    normalize_procurement_stage,
    resolve_bulk_line_items,
)
from app.services.search import find_products, get_results
from app.services.pricing import resolve_price_for_quantity
from app.core.cache import get_cached_data

logger = logging.getLogger(__name__)

# Buyer-facing strings are English-only today. This hook makes the current
# assumption observable and provides a routing point for future translations.
SUPPORTED_LANGUAGES = {"en"}
FUZZY_SELECTION_THRESHOLD = 82
FUZZY_SELECTION_MARGIN = 8
ENTRY_MENU_WORDS = {
    "hi",
    "hello",
    "hey",
    "good morning",
    "good afternoon",
    "good evening",
    "start",
    "menu",
    "help",
}
QUANTITY_QUERY_PATTERN = re.compile(
    r"^(.+?)(?:,\s*|\s+)(\d+)\s+"
    r"(boxes?|packs?|units?|pieces?|pairs?|cartons?|bottles?|rolls?|sets?)$",
    re.IGNORECASE,
)


def _detect_language(sender: str, text: str) -> str:
    """Placeholder for future language detection; English is currently supported."""
    return "en"


def _same_whatsapp_number(left: str | None, right: str | None) -> bool:
    if not left or not right:
        return False
    return left.strip().lstrip("+") == right.strip().lstrip("+")


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
    return (
        f"I received your {message_type}, but this procurement flow works best with typed text right now.\n\n"
        "Please type your reply as text so I can keep helping you. You can also send 0 to return to the main menu."
    )


def _main_menu() -> str:
    return (
        "Welcome to SocioMed.\n\n"
        "Check medical-supply availability or request a formal PFI.\n\n"
        "Reply with a number:\n"
        "1. Check price and availability\n"
        "2. Request formal PFI\n"
        "3. Talk to sales"
    )


def _help_message() -> str:
    return (
        "How SocioMed works:\n"
        "1. Search a product such as surgical gloves or oxygen mask.\n"
        "2. View featured offers when you want a quick shortlist.\n"
        "3. Request a quotation and we notify the supplier or sales team.\n"
        "4. Talk to sales for urgent or complex sourcing needs.\n"
        "6. Browse by category when you want to scan product families first.\n\n"
        "Use 0 at any time to return to the main menu."
    )


def _procurement_stage_prompt() -> str:
    return (
        "Which best describes this request?\n"
        "1. Budgeting / market research\n"
        "2. Awaiting internal approval\n"
        "3. Ready to purchase\n"
        "4. Tender\n"
        "5. General market sourcing"
    )


def _extract_product_query_and_quantity(text: str) -> tuple[str, int | None]:
    match = QUANTITY_QUERY_PATTERN.fullmatch(text.strip())
    if not match:
        return text.strip(), None
    product_query, quantity_text, _uom_text = match.groups()
    return product_query.strip(" ,"), int(quantity_text)


def _stock_verification_status(selected: dict, quantity: int) -> str:
    if not selected.get("is_own_inventory"):
        return "partner_confirmation_required"
    stock_quantity = selected.get("stock_qty")
    if isinstance(stock_quantity, int) and stock_quantity >= quantity:
        return "verified_in_stock"
    if isinstance(stock_quantity, int) and stock_quantity > 0:
        return "insufficient_stock"
    return "out_of_stock"


def _price_action_message(selected: dict, quantity: int, currency: str) -> tuple[str, object]:
    resolution = resolve_price_for_quantity(selected.get("pricing", []), quantity, currency)
    if resolution.eligible:
        price_summary = (
            f"Unit price: {format_price(resolution.unit_price, currency)} per {selected.get('uom') or 'unit'}\n"
            f"Line total: {format_price(resolution.unit_price * quantity, currency)}"
        )
    else:
        price_summary = (
            "We cannot safely confirm an automated price for that quantity. "
            "Sales will review the pricing before any formal PFI is issued."
        )
    message = (
        f"{price_summary}\n\n"
        "Reply with:\n"
        "1. Request formal PFI\n"
        "2. Talk to sales\n"
        "3. Back to search results\n"
        "0. Main menu"
    )
    return message, resolution


def _direct_rfq_prompt() -> str:
    return (
        "Reply with your RFQ in one message: your name, then item(s), quantity, facility, and delivery location.\n\n"
        "Single item:\n"
        "Dr. Ali | surgical gloves | 10 | Mulago Hospital | Kampala | ready_to_purchase\n\n"
        "Bulk list:\n"
        "Dr. Ali | gloves x10, catheters x5, IV sets x20 | Mulago Hospital | Kampala | tender\n\n"
        "Stage options: budgeting, approval_stage, ready_to_purchase, tender, market_sourcing"
    )


def _featured_offers_message(currency: str) -> str:
    offers = get_featured_catalog(limit=MAX_VISIBLE_OFFERS, currency=currency)
    if not offers:
        return "No featured offers are available right now. Reply 1 to search the catalog."

    lines = ["Featured procurement offers:\n"]
    for index, offer in enumerate(offers[:MAX_VISIBLE_OFFERS], start=1):
        starting_price = offer.get("starting_price")
        price_text = format_price(starting_price, currency) if starting_price is not None else "Price on request"
        uom = offer.get("uom") or "unit"
        stock_status = "In Stock" if (offer.get("stock_qty") or 0) > 0 else "Out of Stock"
        lines.append(
            f"{index}. {offer['product_name']} - {offer['brand']}\n"
            f"{price_text} per {uom} | {stock_status} | Lead time {offer.get('lead_time_days', 'N/A')} days\n"
            f"Offer validity: {OFFER_VALIDITY_DAYS} days"
        )

    lines.append(f"\n{OFFER_OVERFLOW_LINE}")
    lines.append("Reply with the product name you want to search, or reply 3 to request a quotation.")
    return "\n\n".join(lines)


def _browse_categories_message(categories: list[str]) -> str:
    if not categories:
        return "No catalog categories are available right now. Reply 1 to search directly or 3 to request a quotation."

    lines = ["Browse procurement categories:\n"]
    for index, category in enumerate(categories, start=1):
        lines.append(f"{index}. {category.title()}")

    lines.append("\nReply with the category number or exact category name.")
    lines.append("Use 0 at any time to return to the main menu.")
    return "\n".join(lines)


def _category_products_message(category_name: str, products: list[Dict], display_limit: int = 12) -> str:
    if not products:
        return (
            f"We do not have products listed in {category_name.title()} yet.\n"
            "Reply with another category number, or use 0 to return to the main menu."
        )

    display_products = products[:display_limit]
    lines = [f"{category_name.title()} products:\n"]
    for index, product in enumerate(display_products, start=1):
        lines.append(f"{index}. {product['name']}")

    if len(products) > display_limit:
        lines.append("")
        lines.append("Type the exact product name if you do not see it in the numbered list.")

    lines.append("")
    lines.append("Reply with the product number you want to price first, or type the exact product name.")
    lines.append("Use 0 at any time to return to the main menu.")
    return "\n".join(lines)


def _append_related_products(reply: str, product: Dict, currency: str) -> tuple[str, list[Dict]]:
    if not ENABLE_RELATED_PRODUCTS:
        return reply, []
    try:
        related_products = get_related_catalog(product.get("product_id", ""), limit=3, currency=currency)
    except Exception as exc:
        logger.warning("related_products_unavailable product_id=%s error=%s", product.get("product_id"), exc)
        return reply, []
    if not related_products:
        return reply, []

    lines = [reply, "", "Complete this order with:"]
    for index, related in enumerate(related_products, start=1):
        price = related.get("starting_price")
        price_text = format_price(price, currency) if price is not None else "Price on request"
        lines.append(f"R{index}. {related['product_name']} from {price_text} per {related.get('uom') or 'unit'}")
    lines.append("Reply with R1, R2, or R3 to view that related item.")
    return "\n".join(lines), related_products


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


def _resolve_category_product_selection(text: str, category_name: str, displayed_products: list[Dict]) -> Optional[Dict]:
    if text.isdigit():
        index = int(text) - 1
        if 0 <= index < len(displayed_products):
            return displayed_products[index]
        return None

    normalized_text = text.strip().lower()
    category_products = get_products_by_category(category_name)

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
    uom: Optional[str] = None,
    unit_price: Optional[int] = None,
    items: Optional[list[dict]] = None,
    procurement_stage: str = "market_sourcing",
    request_formal_pfi: bool = False,
    manual_review_required: bool = False,
    manual_review_reason: Optional[str] = None,
) -> tuple[int, bool, bool, Optional[str]]:
    db = SessionLocal()
    try:
        resolved_items = items or [
            {
                "product_id": product_id,
                "product_name": product_name,
                "inventory_id": None,
                "vendor_id": vendor_id,
                "vendor_name": vendor_name,
                "quantity": quantity,
                "uom": uom,
                "unit_price": unit_price,
                "currency": currency,
            }
        ]
        rfq = create_rfq_request(
            db,
            RFQCreate(
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
                procurement_stage=procurement_stage,
                notes=notes,
                currency=currency,
                source=source,
                items=resolved_items,
                request_formal_pfi=request_formal_pfi,
                manual_review_required=manual_review_required,
                manual_review_reason=manual_review_reason,
            ),
        )
        pfi_result = (
            await generate_pfi_for_eligible_rfq(db, rfq)
            if request_formal_pfi
            else None
        )
    finally:
        db.close()

    supplier_notified = await dispatch_rfq_notifications(rfq, vendor_phone)
    return (
        rfq.id,
        supplier_notified,
        bool(pfi_result and pfi_result.generated),
        pfi_result.reason if pfi_result else None,
    )


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
    if _same_whatsapp_number(sender, SALES_AGENT_PHONE):
        if text is not None:
            db = SessionLocal()
            try:
                await handle_operator_pfi_command(db, sender, text)
            finally:
                db.close()
        return

    if text is None:
        log_audit_event(
            sender,
            "unsupported_whatsapp_message",
            {"message_type": message.get("type", "unknown")},
        )
        await send_whatsapp_message(sender, _unsupported_message_reply(message))
        return

    text_clean = text.lower().strip()
    language = _detect_language(sender, text)
    logger.debug("assumed_language sender=%s language=%s", sender, language)
    currency = get_currency_for_phone(sender)

    session = get_session(sender) or {}
    current_state = session.get("state", ConversationState.MENU.value)
    if not validate_state(current_state):
        logger.warning("invalid_state sender=%s state=%s", sender, current_state)
        current_state = ConversationState.MENU.value
    _log_user_input(sender, current_state, text)

    if not validate_whatsapp_message(text):
        await send_whatsapp_message(sender, "Please send a shorter message using normal text, numbers, and punctuation.")
        return

    session_expired = not session and has_seen_before(sender)
    if text_clean in {"0", "m", "back", "reset", *ENTRY_MENU_WORDS}:
        prefix = (
            "Your previous session timed out, so the unfinished conversation was reset.\n\n"
            if session_expired
            else ""
        )
        await send_whatsapp_message(sender, prefix + _main_menu())
        _transition_session(sender, current_state, ConversationState.MENU)
        return

    if text_clean == "more":
        await send_whatsapp_message(
            sender,
            "Reply with: name | organization | what you need.\n"
            "We will connect you with sales.",
        )
        _transition_session(sender, current_state, ConversationState.TALK_TO_AGENT)
        return

    if not session or current_state == ConversationState.IDLE.value:
        if is_bulk_request(text):
            await send_whatsapp_message(
                sender,
                "This looks like a multi-item sourcing request, so sales must review it safely.\n\n"
                + _direct_rfq_prompt(),
            )
            _transition_session(
                sender,
                current_state,
                ConversationState.DIRECT_RFQ,
                request_formal_pfi=False,
                force_manual_review=True,
                manual_review_reason="multi_item_sourcing_list",
            )
            return

        product_query, requested_quantity = _extract_product_query_and_quantity(text)
        if not validate_product_query(product_query):
            await send_whatsapp_message(sender, _main_menu())
            _transition_session(sender, current_state, ConversationState.MENU)
            return
        text = product_query
        text_clean = product_query.lower()
        current_state = ConversationState.SEARCHING.value
        session = {
            "state": current_state,
            "requested_quantity": requested_quantity,
        }
        _transition_session(
            sender,
            ConversationState.IDLE.value,
            ConversationState.SEARCHING,
            requested_quantity=requested_quantity,
        )

    if current_state == ConversationState.MENU.value:
        if text_clean == "1":
            await send_whatsapp_message(
                sender,
                "Please type the product you want to source, for example surgical gloves, IV set, or oxygen mask.",
            )
            _transition_session(sender, current_state, ConversationState.SEARCHING)
            return
        if text_clean == "2":
            await send_whatsapp_message(sender, _direct_rfq_prompt())
            _transition_session(
                sender,
                current_state,
                ConversationState.DIRECT_RFQ,
                request_formal_pfi=True,
            )
            return
        if text_clean == "3":
            await send_whatsapp_message(
                sender,
                "Reply with: name | organization | what you need.\n"
                "Example: Amina | City Care Hospital | Need 500 gloves urgently",
            )
            _transition_session(sender, current_state, ConversationState.TALK_TO_AGENT)
            return
        if not LAUNCH_MODE and ENABLE_FEATURED_OFFERS and text_clean == "4":
            await send_whatsapp_message(sender, _featured_offers_message(currency))
            _transition_session(sender, current_state, ConversationState.SEARCHING)
            return
        if not LAUNCH_MODE and ENABLE_CATEGORY_BROWSE and text_clean == "5":
            categories = get_categories()
            record_funnel_event(
                "browse_categories",
                source="whatsapp",
                actor_id=sender,
                data={"category_count": len(categories)},
            )
            await send_whatsapp_message(sender, _browse_categories_message(categories))
            _transition_session(
                sender,
                current_state,
                ConversationState.BROWSING_CATEGORIES,
                categories=categories,
            )
            return

        if is_bulk_request(text):
            await send_whatsapp_message(sender, _direct_rfq_prompt())
            _transition_session(
                sender,
                current_state,
                ConversationState.DIRECT_RFQ,
                force_manual_review=True,
                manual_review_reason="multi_item_sourcing_list",
            )
            return
        product_query, requested_quantity = _extract_product_query_and_quantity(text)
        if validate_product_query(product_query):
            text = product_query
            text_clean = product_query.lower()
            current_state = ConversationState.SEARCHING.value
            session = {"state": current_state, "requested_quantity": requested_quantity}
            _transition_session(
                sender,
                ConversationState.MENU.value,
                ConversationState.SEARCHING,
                requested_quantity=requested_quantity,
            )
        else:
            await send_whatsapp_message(sender, "Please reply with 1, 2, or 3, or type a product name.")
            return

    if current_state == ConversationState.SEARCHING.value:
        if is_bulk_request(text):
            detail = "This looks like a multi-item sourcing list, so we'll capture and route it as one RFQ."
            if is_complex_bulk_request(text):
                detail = "This looks like a larger bulk sourcing list, so we'll capture and route it as one RFQ."
            await send_whatsapp_message(
                sender,
                f"{detail}\n\n{_direct_rfq_prompt()}",
            )
            _transition_session(
                sender,
                current_state,
                ConversationState.DIRECT_RFQ,
                force_manual_review=True,
                manual_review_reason="multi_item_sourcing_list",
            )
            return

        if not validate_product_query(text):
            await send_whatsapp_message(
                sender,
                "Please enter a clear product search such as surgical gloves, IV set, or oxygen mask.",
            )
            return

        data = get_cached_data()
        product_matches = find_products(text, data.get("products", []), data.get("aliases", []), limit=5, data=data)
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
                requested_quantity=session.get("requested_quantity"),
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
            await send_whatsapp_message(
                sender,
                "I could not find that exact product. Try another search term, or reply 3 from the main menu to request a quotation.",
            )
            _transition_session(sender, current_state, ConversationState.SEARCHING)
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
            await send_whatsapp_message(
                sender,
                "We do not have a live offer for that product right now. Reply 3 from the main menu to request a quotation anyway.",
            )
            _transition_session(sender, current_state, ConversationState.MENU)
            return

        reply, option_map = format_results(product["name"], results, currency=currency)
        reply, related_products = _append_related_products(reply, product, currency)
        _transition_session(
            sender,
            current_state,
            ConversationState.VIEWING_RESULTS,
            product=product,
            options=option_map,
            related_products=related_products,
            requested_quantity=session.get("requested_quantity"),
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
            await send_whatsapp_message(
                sender,
                "Reply with: name | organization | what you need.\n"
                "We will connect you with sales.",
            )
            _transition_session(sender, current_state, ConversationState.TALK_TO_AGENT)
            return

        try:
            selected_index = int(text_clean) - 1
        except ValueError:
            selected_index = -1

        if selected_index < 0 or selected_index >= len(search_matches):
            await send_whatsapp_message(
                sender,
                "Please reply with one of the product numbers shown, RFQ for a manual quotation, or AGENT for sales.",
            )
            return

        selected_product = search_matches[selected_index]
        data = get_cached_data()
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
            await send_whatsapp_message(
                sender,
                "We do not have a live offer for that product right now.\n"
                "Reply RFQ to request a manual quotation, or AGENT for a sourcing handoff.",
            )
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
            requested_quantity=session.get("requested_quantity"),
        )
        await send_whatsapp_message(sender, reply)
        return

    if current_state == ConversationState.BROWSING_CATEGORIES.value:
        categories = session.get("categories") or get_categories()
        selected_category = _resolve_category_selection(text_clean, categories)
        if not selected_category:
            await send_whatsapp_message(
                sender,
                "Please reply with one of the category numbers shown, or type the exact category name.",
            )
            return

        category_products = get_products_by_category(selected_category)
        displayed_products = category_products[:12]
        record_funnel_event(
            "results",
            source="whatsapp",
            actor_id=sender,
            data={
                "channel": "category_browse",
                "category": selected_category,
                "result_count": len(category_products),
            },
        )
        await send_whatsapp_message(sender, _category_products_message(selected_category, category_products))
        _transition_session(
            sender,
            current_state,
            ConversationState.CATEGORY_SELECTED,
            category_name=selected_category,
            category_products=displayed_products,
        )
        return

    if current_state == ConversationState.CATEGORY_SELECTED.value:
        category_name = session.get("category_name", "")
        displayed_products = session.get("category_products", [])
        selected_product = _resolve_category_product_selection(text, category_name, displayed_products)
        if not selected_product:
            await send_whatsapp_message(
                sender,
                "Please reply with one of the product numbers shown, or type the exact product name from that category.",
            )
            return

        data = get_cached_data()
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
            await send_whatsapp_message(
                sender,
                "We do not have a live offer for that product right now.\n"
                "Reply with another product number, type another product name, or use 3 from the main menu to request a quotation.",
            )
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
                await send_whatsapp_message(sender, "That related item is not available. Reply with an offer number or 0 for menu.")
                return

            selected_related = related_products[related_index]
            data = get_cached_data()
            products_by_id = data.get("products_by_id") or {
                product["product_id"]: product for product in data.get("products", [])
            }
            selected_product = products_by_id.get(selected_related.get("product_id"))
            if not selected_product:
                await send_whatsapp_message(sender, "That related item is no longer available. Reply 0 for the main menu.")
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
                await send_whatsapp_message(sender, "We do not have a live offer for that related item right now.")
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
            await send_whatsapp_message(sender, "Reply with the offer number you want, or 0 for the main menu.")
            return

        options = session.get("options", [])
        if 1 <= option_num <= len(options):
            selected = options[option_num - 1]
            requested_quantity = session.get("requested_quantity")
            if requested_quantity:
                price_message, resolution = _price_action_message(selected, requested_quantity, currency)
                _transition_session(
                    sender,
                    current_state,
                    ConversationState.VIEWING_PRICE,
                    product=session.get("product"),
                    options=options,
                    selected_item=selected,
                    quantity=requested_quantity,
                    unit_price=resolution.unit_price,
                    price_source=resolution.pricing_id,
                    pricing_reason=resolution.reason_code,
                )
                await send_whatsapp_message(sender, price_message)
                return
            _transition_session(
                sender,
                current_state,
                ConversationState.SELECTING_PRODUCT,
                product=session.get("product"),
                options=options,
                selected_item=selected,
                requested_quantity=None,
            )
            await send_whatsapp_message(
                sender,
                f"You selected {selected['brand']}.\n"
                f"UoM: {selected.get('uom', 'unit')}\n"
                f"Stock: {'In Stock' if (selected.get('stock_qty') or 0) > 0 else 'Out of Stock'}\n\n"
                f"How many {selected.get('uom', 'unit')} do you need?",
            )
            return

        await send_whatsapp_message(sender, "That option is not available. Reply with one of the offer numbers shown.")
        return

    if current_state == ConversationState.SELECTING_PRODUCT.value:
        try:
            quantity = int(text_clean)
        except ValueError:
            await send_whatsapp_message(sender, "Please reply with a quantity as a whole number.")
            return

        if not validate_quantity(quantity):
            await send_whatsapp_message(sender, "Please reply with a quantity greater than zero.")
            return

        selected = session.get("selected_item", {})
        minimum_quantity = selected.get("min_qty", 1)
        if quantity < minimum_quantity:
            await send_whatsapp_message(
                sender,
                "That quantity is unavailable for this offer. Reply with a different whole-number quantity.",
            )
            return

        price_message, resolution = _price_action_message(selected, quantity, currency)

        _transition_session(
            sender,
            current_state,
            ConversationState.VIEWING_PRICE,
            product=session.get("product"),
            options=session.get("options", []),
            selected_item=selected,
            quantity=quantity,
            unit_price=resolution.unit_price,
            price_source=resolution.pricing_id,
            pricing_reason=resolution.reason_code,
        )
        await send_whatsapp_message(sender, price_message)
        return

    if current_state == ConversationState.VIEWING_PRICE.value:
        if text_clean == "1":
            await send_whatsapp_message(
                sender,
                "Reply with your name, facility/client name, and delivery location.\n"
                "Example: Dr. Ali, Mulago Hospital, Kampala",
            )
            _transition_session(
                sender,
                current_state,
                ConversationState.RFQ_FLOW,
                product=session.get("product"),
                selected_item=session.get("selected_item"),
                quantity=session.get("quantity"),
                unit_price=session.get("unit_price"),
                price_source=session.get("price_source"),
                pricing_reason=session.get("pricing_reason"),
            )
            return
        if text_clean == "2":
            await send_whatsapp_message(
                sender,
                "Reply with: name | organization | what you need.\n"
                "We will connect you with sales.",
            )
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
            await send_whatsapp_message(sender, "Returning to the available offers.")
            return

        await send_whatsapp_message(sender, "Please reply with 1, 2, 3, or 0.")
        return

    if current_state == ConversationState.RFQ_FLOW.value:
        contact_name, organization, delivery_location = _parse_buyer_facility_details(text)

        if (
            not validate_contact_name(contact_name)
            or not validate_facility_name(organization)
            or not validate_delivery_location(delivery_location)
        ):
            await send_whatsapp_message(
                sender,
                "Please reply with your name, facility/client name, and delivery location.\n"
                "Example: Dr. Ali, Mulago Hospital, Kampala",
            )
            return

        await send_whatsapp_message(sender, _procurement_stage_prompt())
        _transition_session(
            sender,
            current_state,
            ConversationState.QUALIFYING_INTENT,
            buyer_name=contact_name,
            organization=organization,
            delivery_location=delivery_location,
            product=session.get("product"),
            selected_item=session.get("selected_item"),
            quantity=session.get("quantity", 1),
            unit_price=session.get("unit_price"),
            price_source=session.get("price_source"),
            pricing_reason=session.get("pricing_reason"),
        )
        return

    if current_state == ConversationState.QUALIFYING_INTENT.value:
        procurement_stage = normalize_procurement_stage(text)
        if not procurement_stage:
            await send_whatsapp_message(sender, _procurement_stage_prompt())
            return

        selected = session.get("selected_item", {})
        product = session.get("product", {})
        quantity = session.get("quantity", 1)
        resolution = resolve_price_for_quantity(selected.get("pricing", []), quantity, currency)
        stock_status = _stock_verification_status(selected, quantity)
        manual_reason = resolution.reason_code if not resolution.eligible else None
        try:
            creation_result = await _create_whatsapp_rfq(
                sender=sender,
                buyer_name=session.get("buyer_name", ""),
                product_name=product.get("name", selected.get("brand", "Medical supply")),
                quantity=quantity,
                organization=session.get("organization", ""),
                delivery_location=session.get("delivery_location", ""),
                source="whatsapp_selected_offer",
                product_id=product.get("product_id"),
                vendor_id=selected.get("vendor_id"),
                vendor_name=selected.get("vendor_name"),
                vendor_phone=selected.get("vendor_phone"),
                notes=(
                    f"Selected brand: {selected.get('brand', 'Generic')} | "
                    f"SKU: {selected.get('sku') or 'N/A'} | "
                    f"UoM: {selected.get('uom', 'unit')}"
                ),
                currency=currency,
                uom=selected.get("uom"),
                unit_price=resolution.unit_price,
                procurement_stage=procurement_stage,
                request_formal_pfi=True,
                manual_review_required=not resolution.eligible,
                manual_review_reason=manual_reason,
                items=[
                    {
                        "inventory_id": selected.get("inventory_id"),
                        "product_id": product.get("product_id"),
                        "product_name": product.get("name", selected.get("brand", "Medical supply")),
                        "brand": selected.get("brand"),
                        "sku": selected.get("sku"),
                        "item_type": product.get("item_type") or "generic",
                        "vendor_id": selected.get("vendor_id"),
                        "vendor_name": selected.get("vendor_name"),
                        "is_own_inventory": bool(selected.get("is_own_inventory")),
                        "quantity": quantity,
                        "uom": selected.get("uom"),
                        "unit_price": resolution.unit_price,
                        "currency": currency,
                        "price_source": resolution.pricing_id,
                        "stock_verification_status": stock_status,
                    }
                ],
            )
            rfq_id, supplier_notified = creation_result[:2]
            pfi_generated = creation_result[2] if len(creation_result) > 2 else False
            pfi_reason = creation_result[3] if len(creation_result) > 3 else None
        except Exception as exc:
            log_audit_event(sender, "whatsapp_rfq_failed", {"error": str(exc)})
            await send_whatsapp_message(sender, "We could not submit your quotation request right now. Please try again shortly.")
            _transition_session(sender, current_state, ConversationState.MENU)
            return

        routing_text = (
            "Operations has received the request."
            if supplier_notified
            else "Our sales team will route it manually."
        )
        pfi_text = (
            "Your formal PFI is ready."
            if pfi_generated
            else "A sales specialist must verify the request before a formal PFI is issued."
        )
        await send_whatsapp_message(
            sender,
            f"Quotation request received. RFQ #{rfq_id} has been created.\n"
            f"{routing_text}\n{pfi_text}",
        )
        log_audit_event(
            sender,
            "whatsapp_rfq_qualified",
            {"rfq_id": rfq_id, "procurement_stage": procurement_stage, "pfi_reason": pfi_reason},
        )
        _transition_session(sender, current_state, ConversationState.MENU)
        return

    if current_state == ConversationState.DIRECT_RFQ.value:
        rfq_payload = parse_direct_rfq_message(text)
        if not rfq_payload:
            await send_whatsapp_message(
                sender,
                "Please use one of these formats:\n\n"
                "Single item:\n"
                "Dr. Ali | surgical gloves | 10 | Mulago Hospital | Kampala | ready_to_purchase\n\n"
                "Bulk list:\n"
                "Dr. Ali | gloves x10, catheters x5, IV sets x20 | Mulago Hospital | Kampala | tender",
            )
            return

        if (
            not validate_contact_name(rfq_payload.buyer_name)
            or not validate_quantity(rfq_payload.quantity)
            or not validate_facility_name(rfq_payload.organization)
            or not validate_delivery_location(rfq_payload.delivery_location)
        ):
            await send_whatsapp_message(
                sender,
                "Please send a valid name, quantity, facility/client name, and delivery location.",
            )
            return
        try:
            data = get_cached_data()
            resolved_items = resolve_bulk_line_items(
                list(rfq_payload.requested_items),
                data,
                currency=currency,
                default_quantity=rfq_payload.quantity if not rfq_payload.is_bulk else 1,
            )
            primary_vendor_phone = resolved_items[0].get("vendor_phone") if resolved_items else None
            creation_result = await _create_whatsapp_rfq(
                sender=sender,
                buyer_name=rfq_payload.buyer_name,
                product_name=rfq_payload.product_name,
                quantity=rfq_payload.quantity,
                organization=rfq_payload.organization,
                delivery_location=rfq_payload.delivery_location,
                source=rfq_payload.source,
                notes=rfq_payload.notes,
                currency=currency,
                vendor_phone=primary_vendor_phone,
                items=resolved_items,
                procurement_stage=rfq_payload.procurement_stage,
                request_formal_pfi=bool(session.get("request_formal_pfi")),
                manual_review_required=bool(session.get("force_manual_review")) or rfq_payload.is_bulk,
                manual_review_reason=(
                    session.get("manual_review_reason")
                    or ("multi_item_sourcing_list" if rfq_payload.is_bulk else None)
                ),
            )
            rfq_id = creation_result[0]
            pfi_generated = creation_result[2] if len(creation_result) > 2 else False
        except Exception as exc:
            log_audit_event(sender, "direct_whatsapp_rfq_failed", {"error": str(exc)})
            await send_whatsapp_message(sender, "We could not capture your quotation request right now. Please try again.")
            _transition_session(sender, current_state, ConversationState.MENU)
            return

        if rfq_payload.is_bulk:
            log_audit_event(
                sender,
                "bulk_rfq_triaged",
                {"rfq_id": rfq_id, "item_count": rfq_payload.item_count, "source": rfq_payload.source},
            )
            await send_whatsapp_message(
                sender,
                f"Your bulk quotation request has been logged as RFQ #{rfq_id}.\n"
                "The list has been routed to sales for verification. "
                + (
                    "Your formal PFI is ready."
                    if pfi_generated
                    else "No automated PFI was issued. Sales will confirm stock, pricing and lead time."
                ),
            )
            _transition_session(sender, current_state, ConversationState.MENU)
            return

        await send_whatsapp_message(
            sender,
            f"Your quotation request has been logged as RFQ #{rfq_id}.\n"
            + (
                "Your formal PFI is ready."
                if pfi_generated
                else "Sales will verify the request before issuing any formal PFI."
            ),
        )
        _transition_session(sender, current_state, ConversationState.MENU)
        return

    if current_state == ConversationState.TALK_TO_AGENT.value:
        try:
            lead_id = await _capture_sales_lead(sender, text, "whatsapp_sales_handoff")
        except Exception as exc:
            log_audit_event(sender, "sales_lead_failed", {"error": str(exc)})
            await send_whatsapp_message(sender, "We could not hand this off to sales right now. Please try again shortly.")
            _transition_session(sender, current_state, ConversationState.MENU)
            return

        await send_whatsapp_message(
            sender,
            f"Your request has been shared with our sales team. Lead #{lead_id} is now open and someone will reach out shortly.",
        )
        _transition_session(sender, current_state, ConversationState.MENU)
        return

    await send_whatsapp_message(sender, "I did not understand that. Reply 0 for the main menu.")
