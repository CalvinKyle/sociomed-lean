import logging
import re
from typing import Dict, Optional

from app.core.currency import format_price, get_currency_for_phone
from app.core.states import ConversationState
from app.core.utils import get_session, log_audit_event, save_session, send_whatsapp_message
from app.core.validators import (
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
from app.models.formatter import format_results
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
)
from app.services.search import find_products, get_results
from app.core.cache import get_cached_data

logger = logging.getLogger(__name__)


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
        "We help procurement teams source medical supplies faster through WhatsApp.\n\n"
        "Reply with a number:\n"
        "1. Search for a product\n"
        "2. View featured offers\n"
        "3. Request a quotation\n"
        "4. Talk to sales\n"
        "5. Help\n"
        "6. Browse by category"
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


def _direct_rfq_prompt() -> str:
    return (
        "Reply with your RFQ in one message.\n\n"
        "Single item:\n"
        "surgical gloves | 10 | Mulago Hospital | Kampala\n\n"
        "Bulk list:\n"
        "gloves x10, catheters x5, IV sets x20 | Mulago Hospital | Kampala"
    )


def _featured_offers_message(currency: str) -> str:
    offers = get_featured_catalog(limit=4)
    if not offers:
        return "No featured offers are available right now. Reply 1 to search the catalog."

    lines = ["Featured procurement offers:\n"]
    for index, offer in enumerate(offers, start=1):
        starting_price = offer.get("starting_price")
        price_text = format_price(starting_price, currency) if starting_price is not None else "Price on request"
        uom = offer.get("uom") or "unit"
        lines.append(
            f"{index}. {offer['product_name']} - {offer['brand']} from {offer.get('vendor_name', 'Supplier')}\n"
            f"From {price_text} per {uom} | Stock {offer.get('stock_qty', 0)} | Lead time {offer.get('lead_time_days', 'N/A')} days"
        )

    lines.append("\nReply with the product name you want to search, or reply 3 to request a quotation.")
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
    try:
        related_products = get_related_catalog(product.get("product_id", ""), limit=3, currency=currency)
    except Exception as exc:
        logger.warning("related_products_unavailable product_id=%s error=%s", product.get("product_id"), exc)
        return reply, []
    if not related_products:
        return reply, []

    lines = [reply, "", "Often sourced with this item:"]
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

    return None


def _split_pipe_message(text: str) -> list[str]:
    return [part.strip() for part in text.split("|") if part.strip()]


def _parse_buyer_intro(text: str, sender: str) -> tuple[str, str, str]:
    parts = _split_pipe_message(text)
    buyer_name = parts[0] if parts else sender
    organization = parts[1] if len(parts) > 1 else "WhatsApp buyer"
    need = parts[2] if len(parts) > 2 else text.strip()
    return buyer_name, organization, need


def _parse_facility_details(text: str) -> tuple[str, str]:
    parts = [part.strip() for part in re.split(r"\n|,", text) if part.strip()]
    if not parts:
        return "WhatsApp buyer", "Location not provided"
    if len(parts) == 1:
        return parts[0], parts[0]
    return parts[0], ", ".join(parts[1:])


def _log_user_input(sender: str, state: str, text: str) -> None:
    logger.info("whatsapp_input sender=%s state=%s text=%s", sender, state, text[:200])


def _transition_session(sender: str, current_state: str, next_state: ConversationState, **payload) -> None:
    logger.info("state_transition sender=%s from=%s to=%s", sender, current_state, next_state.value)
    session_payload = {"state": next_state.value}
    session_payload.update(payload)
    save_session(sender, session_payload)


async def _create_whatsapp_rfq(
    sender: str,
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
) -> tuple[int, bool]:
    db = SessionLocal()
    try:
        rfq = create_rfq_request(
            db,
            RFQCreate(
                buyer_name=sender,
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
            ),
        )
    finally:
        db.close()

    supplier_notified = await dispatch_rfq_notifications(rfq, vendor_phone)
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

    if text_clean in ["0", "m", "menu", "back"]:
        await send_whatsapp_message(sender, _main_menu())
        _transition_session(sender, current_state, ConversationState.MENU)
        return

    if not session or current_state == ConversationState.IDLE.value:
        await send_whatsapp_message(sender, _main_menu())
        _transition_session(sender, current_state, ConversationState.MENU)
        return

    if current_state == ConversationState.MENU.value:
        if text_clean == "1":
            await send_whatsapp_message(
                sender,
                "Please type the product you want to source, for example surgical gloves, IV set, or oxygen mask.",
            )
            _transition_session(sender, current_state, ConversationState.SEARCHING)
            return
        if text_clean == "2":
            await send_whatsapp_message(sender, _featured_offers_message(currency))
            _transition_session(sender, current_state, ConversationState.SEARCHING)
            return
        if text_clean == "3":
            await send_whatsapp_message(sender, _direct_rfq_prompt())
            _transition_session(sender, current_state, ConversationState.DIRECT_RFQ)
            return
        if text_clean == "4":
            await send_whatsapp_message(
                sender,
                "Reply with: name | organization | what you need.\n"
                "Example: Amina | City Care Hospital | Need 500 gloves urgently",
            )
            _transition_session(sender, current_state, ConversationState.TALK_TO_AGENT)
            return
        if text_clean == "5":
            await send_whatsapp_message(sender, _help_message())
            _transition_session(sender, current_state, ConversationState.MENU)
            return
        if text_clean == "6":
            categories = get_categories()
            await send_whatsapp_message(sender, _browse_categories_message(categories))
            _transition_session(
                sender,
                current_state,
                ConversationState.BROWSING_CATEGORIES,
                categories=categories,
            )
            return

        await send_whatsapp_message(sender, "Please reply with a number from 1 to 6.")
        return

    if current_state == ConversationState.SEARCHING.value:
        if is_bulk_request(text):
            detail = (
                "This looks like a multi-item sourcing list, so we should capture it as one RFQ for manual routing."
            )
            if is_complex_bulk_request(text):
                detail = "This looks like a larger bulk sourcing list, so a SocioMed agent should triage it as one RFQ."
            await send_whatsapp_message(
                sender,
                f"{detail}\n\n{_direct_rfq_prompt()}",
            )
            _transition_session(sender, current_state, ConversationState.DIRECT_RFQ)
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
                f"You selected {selected['brand']} from {selected.get('vendor_name', 'Supplier')}.\n"
                f"{sku_line}"
                f"UoM: {selected.get('uom', 'unit')}\n"
                f"Minimum order: {selected.get('min_qty', 1)} {selected.get('uom', 'unit')}\n"
                f"Stock: {selected.get('stock_qty', 0)} {selected.get('uom', 'unit')}\n\n"
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
                f"Minimum order for this offer is {minimum_quantity} {selected.get('uom', 'unit')}.",
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
        await send_whatsapp_message(
            sender,
            f"Estimated starting price: {format_price(selected.get('default_price', 0), currency)} per {selected.get('uom', 'unit')}.\n\n"
            "Reply with:\n"
            "1. Request quotation\n"
            "2. Talk to sales\n"
            "3. Back to search results\n"
            "0. Main menu",
        )
        return

    if current_state == ConversationState.VIEWING_PRICE.value:
        if text_clean == "1":
            await send_whatsapp_message(
                sender,
                "Reply with your facility/client name and delivery location.\n"
                "Example: Mulago Hospital, Kampala",
            )
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
            await send_whatsapp_message(sender, "Returning to the supplier offers.")
            return

        await send_whatsapp_message(sender, "Please reply with 1, 2, 3, or 0.")
        return

    if current_state == ConversationState.RFQ_FLOW.value:
        selected = session.get("selected_item", {})
        product = session.get("product", {})
        quantity = session.get("quantity", 1)
        organization, delivery_location = _parse_facility_details(text)

        if not validate_facility_name(organization) or not validate_delivery_location(delivery_location):
            await send_whatsapp_message(
                sender,
                "Please reply with a valid facility/client name and delivery location.\n"
                "Example: Mulago Hospital, Kampala",
            )
            return

        try:
            rfq_id, supplier_notified = await _create_whatsapp_rfq(
                sender=sender,
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
                    f"Selected brand: {selected.get('brand', 'Generic')} | "
                    f"SKU: {selected.get('sku') or 'N/A'} | "
                    f"UoM: {selected.get('uom', 'unit')}"
                ),
                currency=currency,
            )
        except Exception as exc:
            log_audit_event(sender, "whatsapp_rfq_failed", {"error": str(exc)})
            await send_whatsapp_message(sender, "We could not submit your quotation request right now. Please try again shortly.")
            _transition_session(sender, current_state, ConversationState.MENU)
            return

        supplier_text = "The supplier has been notified." if supplier_notified else "Our sales team will route it manually."
        await send_whatsapp_message(
            sender,
            f"Quotation request received. RFQ #{rfq_id} has been created.\n"
            f"{supplier_text}\n"
            "A follow-up will be shared with you shortly.",
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
                "surgical gloves | 10 | Mulago Hospital | Kampala\n\n"
                "Bulk list:\n"
                "gloves x10, catheters x5, IV sets x20 | Mulago Hospital | Kampala",
            )
            return

        if (
            not validate_quantity(rfq_payload.quantity)
            or not validate_facility_name(rfq_payload.organization)
            or not validate_delivery_location(rfq_payload.delivery_location)
        ):
            await send_whatsapp_message(
                sender,
                "Please send a valid quantity, facility/client name, and delivery location.",
            )
            return
        try:
            rfq_id, _ = await _create_whatsapp_rfq(
                sender=sender,
                product_name=rfq_payload.product_name,
                quantity=rfq_payload.quantity,
                organization=rfq_payload.organization,
                delivery_location=rfq_payload.delivery_location,
                source=rfq_payload.source,
                notes=rfq_payload.notes,
                currency=currency,
            )
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
                "A SocioMed agent will triage the list, match suppliers, and follow up with options.",
            )
            _transition_session(sender, current_state, ConversationState.MENU)
            return

        await send_whatsapp_message(
            sender,
            f"Your quotation request has been logged as RFQ #{rfq_id}.\n"
            "Our team will match it to suppliers and follow up with you.",
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
