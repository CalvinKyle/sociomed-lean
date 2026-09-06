import logging
import re
from typing import Dict, Optional

from rapidfuzz import fuzz

from app.core.conversation_copy import conversation_message
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
from app.data_access.procurement import get_buyer_profile
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
        price_text = format_price(starting_price, currency) if starting_price is not None else "Price on request"
        uom = offer.get("uom") or "unit"
        lines.append(conversation_message(
            "featured_offer",
            index=index,
            product_name=offer["product_name"],
            brand=offer["brand"],
            vendor_name=offer.get("vendor_name", "Supplier"),
            price_text=price_text,
            uom=uom,
            stock_qty=offer.get("stock_qty", 0),
            lead_time_days=offer.get("lead_time_days", "N/A"),
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


def _category_products_message(category_name: str, products: list[Dict], display_limit: int = 12) -> str:
    if not products:
        return conversation_message("category_empty", category_name=category_name.title())

    display_products = products[:display_limit]
    lines = [conversation_message("category_products_header", category_name=category_name.title())]
    for index, product in enumerate(display_products, start=1):
        lines.append(f"{index}. {product['name']}")

    if len(products) > display_limit:
        lines.append("")
        lines.append(conversation_message("category_products_overflow"))

    lines.append("")
    lines.append(conversation_message("category_products_footer"))
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
        price_text = format_price(price, currency) if price is not None else "Price on request"
        lines.append(conversation_message(
            "related_offer",
            index=index,
            product_name=related["product_name"],
            price_text=price_text,
            uom=related.get("uom") or "unit",
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
) -> tuple[int, bool]:
    db = SessionLocal()
    try:
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
                notes=notes,
                currency=currency,
                source=source,
                procurement_stage="formal_purchase",
                formal_quote=True,
                equipment_review_required=equipment_review_required,
                manual_review_reason=manual_review_reason,
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
            category_products = get_products_by_category(entry_intent.category)
            await send_whatsapp_message(
                sender,
                _category_products_message(entry_intent.category, category_products),
            )
            _transition_session(
                sender,
                current_state,
                ConversationState.CATEGORY_SELECTED,
                category_name=entry_intent.category,
                category_products=category_products[:12],
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
            detail = conversation_message("bulk_detected")
            if is_complex_bulk_request(text):
                detail = conversation_message("bulk_complex")
            await send_whatsapp_message(
                sender,
                f"{detail}\n\n{_direct_rfq_prompt()}",
            )
            _transition_session(sender, current_state, ConversationState.DIRECT_RFQ)
            return

        if not validate_product_query(text):
            await send_whatsapp_message(sender, conversation_message("search_invalid"))
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
            await send_whatsapp_message(sender, conversation_message("search_no_match"))
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
            await send_whatsapp_message(sender, conversation_message("category_product_invalid"))
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
                    brand=selected["brand"],
                    sku_line=sku_line,
                    uom=selected.get("uom", "unit"),
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
                    uom=selected.get("uom", "unit"),
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
        await send_whatsapp_message(
            sender,
            conversation_message(
                "price_menu",
                price_text=format_price(selected.get("default_price", 0), currency),
                uom=selected.get("uom", "unit"),
            ),
        )
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
                    f"Selected brand: {selected.get('brand', 'Generic')} | "
                    f"SKU: {selected.get('sku') or 'N/A'} | "
                    f"UoM: {selected.get('uom', 'unit')}"
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
        rfq_payload = parse_direct_rfq_message(
            text,
            buyer_profile=session.get("buyer_profile"),
        )
        if not rfq_payload:
            await send_whatsapp_message(sender, conversation_message("direct_rfq_invalid_format"))
            return

        if (
            not validate_contact_name(rfq_payload.buyer_name)
            or not validate_quantity(rfq_payload.quantity)
            or not validate_facility_name(rfq_payload.organization)
            or not validate_delivery_location(rfq_payload.delivery_location)
        ):
            await send_whatsapp_message(sender, conversation_message("direct_rfq_invalid_data"))
            return
        try:
            rfq_id, _ = await _create_whatsapp_rfq(
                sender=sender,
                buyer_name=rfq_payload.buyer_name,
                product_name=rfq_payload.product_name,
                quantity=rfq_payload.quantity,
                organization=rfq_payload.organization,
                delivery_location=rfq_payload.delivery_location,
                source=rfq_payload.source,
                notes=rfq_payload.notes,
                currency=currency,
                equipment_review_required=is_equipment_product(
                    {"name": rfq_payload.product_name}
                ),
                manual_review_reason=(
                    "complex_multi_item_review"
                    if rfq_payload.is_bulk and is_complex_bulk_request(rfq_payload.product_name)
                    else (
                        "equipment_technical_review"
                        if is_equipment_product({"name": rfq_payload.product_name})
                        else None
                    )
                ),
            )
        except Exception as exc:
            log_audit_event(sender, "direct_whatsapp_rfq_failed", {"error": str(exc)})
            await send_whatsapp_message(sender, conversation_message("direct_rfq_submit_error"))
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
                conversation_message("bulk_rfq_received", rfq_id=rfq_id),
            )
            _transition_session(sender, current_state, ConversationState.MENU)
            return

        await send_whatsapp_message(
            sender,
            conversation_message("direct_rfq_received", rfq_id=rfq_id),
        )
        _transition_session(sender, current_state, ConversationState.MENU)
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
