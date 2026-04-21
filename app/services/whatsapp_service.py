import re
from typing import Dict, Optional

from app.core.currency import format_price, get_currency_for_phone
from app.core.utils import get_session, log_audit_event, save_session, send_whatsapp_message
from app.models.db import SessionLocal
from app.models.formatter import format_results
from app.schemas.schemas import BuyerLeadCreate, RFQCreate
from app.services.catalog import get_featured_catalog
from app.services.procurement import (
    create_buyer_lead,
    create_rfq_request,
    dispatch_lead_notification,
    dispatch_rfq_notifications,
)
from app.services.search import find_product, get_results
from app.core.cache import get_cached_data


def extract_message(body: Dict) -> Optional[Dict]:
    """Safely extract the first inbound WhatsApp message."""
    try:
        return body["entry"][0]["changes"][0]["value"]["messages"][0]
    except (KeyError, IndexError, TypeError):
        return None


def _main_menu() -> str:
    return (
        "Welcome to SocioMed.\n\n"
        "We help procurement teams source medical supplies faster through WhatsApp.\n\n"
        "Reply with a number:\n"
        "1. Search for a product\n"
        "2. View featured offers\n"
        "3. Request a quotation\n"
        "4. Talk to sales\n"
        "5. Help"
    )


def _help_message() -> str:
    return (
        "How SocioMed works:\n"
        "1. Search a product such as surgical gloves or oxygen mask.\n"
        "2. Compare supplier offers by price, stock, and lead time.\n"
        "3. Request a quotation and we notify the supplier or sales team.\n\n"
        "Use 0 at any time to return to the main menu."
    )


def _featured_offers_message(currency: str) -> str:
    offers = get_featured_catalog(limit=4)
    if not offers:
        return "No featured offers are available right now. Reply 1 to search the catalog."

    lines = ["Featured procurement offers:\n"]
    for index, offer in enumerate(offers, start=1):
        starting_price = offer.get("starting_price")
        price_text = format_price(starting_price, currency) if starting_price is not None else "Price on request"
        lines.append(
            f"{index}. {offer['product_name']} - {offer['brand']} from {offer.get('vendor_name', 'Supplier')}\n"
            f"From {price_text} | Stock {offer.get('stock_qty', 0)} | Lead time {offer.get('lead_time_days', 'N/A')} days"
        )

    lines.append("\nReply with the product name you want to search, or reply 3 to request a quotation.")
    return "\n\n".join(lines)


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


def _parse_direct_rfq(text: str) -> Optional[tuple[str, int, str, str]]:
    parts = _split_pipe_message(text)
    if len(parts) < 4:
        return None

    product_name = parts[0]
    quantity_text = parts[1]
    facility = parts[2]
    location = parts[3]

    try:
        quantity = int(quantity_text)
    except ValueError:
        return None

    return product_name, quantity, facility, location


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
    text = message["text"]["body"].strip()
    sender = message["from"]
    text_clean = text.lower()
    currency = get_currency_for_phone(sender)

    session = get_session(sender) or {}
    current_state = session.get("state", "MENU")

    if text_clean in ["0", "m", "menu", "back"]:
        await send_whatsapp_message(sender, _main_menu())
        save_session(sender, {"state": "MENU"})
        return

    if not session or current_state == "IDLE":
        await send_whatsapp_message(sender, _main_menu())
        save_session(sender, {"state": "MENU"})
        return

    if current_state == "MENU":
        if text_clean == "1":
            await send_whatsapp_message(
                sender,
                "Please type the product you want to source, for example surgical gloves, IV set, or oxygen mask.",
            )
            save_session(sender, {"state": "SEARCHING"})
            return
        if text_clean == "2":
            await send_whatsapp_message(sender, _featured_offers_message(currency))
            save_session(sender, {"state": "SEARCHING"})
            return
        if text_clean == "3":
            await send_whatsapp_message(
                sender,
                "Reply in one message using this format:\n"
                "item(s) | quantity | facility/client name | delivery location",
            )
            save_session(sender, {"state": "DIRECT_RFQ"})
            return
        if text_clean == "4":
            await send_whatsapp_message(
                sender,
                "Reply with: name | organization | what you need.\n"
                "Example: Amina | City Care Hospital | Need 500 gloves urgently",
            )
            save_session(sender, {"state": "TALK_TO_AGENT"})
            return
        if text_clean == "5":
            await send_whatsapp_message(sender, _help_message())
            save_session(sender, {"state": "MENU"})
            return

        await send_whatsapp_message(sender, "Please reply with a number from 1 to 5.")
        return

    if current_state == "SEARCHING":
        if "," in text or " and " in text_clean or "+" in text_clean:
            await send_whatsapp_message(
                sender,
                "For multi-item procurement lists, use the quotation flow.\n"
                "Reply with: item(s) | quantity | facility/client name | delivery location",
            )
            save_session(sender, {"state": "DIRECT_RFQ"})
            return

        data = get_cached_data()
        product = find_product(text, data.get("products", []), data.get("aliases", []))
        if not product:
            await send_whatsapp_message(
                sender,
                "I could not find that exact product. Try another search term, or reply 3 from the main menu to request a quotation.",
            )
            save_session(sender, {"state": "SEARCHING"})
            return

        results = get_results(product["product_id"], data)
        if not results:
            await send_whatsapp_message(
                sender,
                "We do not have a live offer for that product right now. Reply 3 from the main menu to request a quotation anyway.",
            )
            save_session(sender, {"state": "MENU"})
            return

        reply, option_map = format_results(product["name"], results, currency=currency)
        save_session(sender, {"state": "VIEWING_RESULTS", "product": product, "options": option_map})
        await send_whatsapp_message(sender, reply)
        return

    if current_state == "VIEWING_RESULTS":
        try:
            option_num = int(text_clean)
        except ValueError:
            await send_whatsapp_message(sender, "Reply with the offer number you want, or 0 for the main menu.")
            return

        options = session.get("options", [])
        if 1 <= option_num <= len(options):
            selected = options[option_num - 1]
            save_session(
                sender,
                {
                    "state": "SELECTING_PRODUCT",
                    "product": session.get("product"),
                    "options": options,
                    "selected_item": selected,
                },
            )
            await send_whatsapp_message(
                sender,
                f"You selected {selected['brand']} from {selected.get('vendor_name', 'Supplier')}.\n"
                f"Minimum order: {selected.get('min_qty', 1)} units\n"
                f"Stock: {selected.get('stock_qty', 0)} units\n\n"
                "How many units do you need?",
            )
            return

        await send_whatsapp_message(sender, "That option is not available. Reply with one of the offer numbers shown.")
        return

    if current_state == "SELECTING_PRODUCT":
        try:
            quantity = int(text_clean)
        except ValueError:
            await send_whatsapp_message(sender, "Please reply with a quantity as a whole number.")
            return

        selected = session.get("selected_item", {})
        minimum_quantity = selected.get("min_qty", 1)
        if quantity < minimum_quantity:
            await send_whatsapp_message(sender, f"Minimum order for this offer is {minimum_quantity} units.")
            return

        save_session(
            sender,
            {
                "state": "VIEWING_PRICE",
                "product": session.get("product"),
                "options": session.get("options", []),
                "selected_item": selected,
                "quantity": quantity,
            },
        )
        await send_whatsapp_message(
            sender,
            f"Estimated starting price: {format_price(selected.get('default_price', 0), currency)} per unit.\n\n"
            "Reply with:\n"
            "1. Request quotation\n"
            "2. Talk to sales\n"
            "3. Back to search results\n"
            "0. Main menu",
        )
        return

    if current_state == "VIEWING_PRICE":
        if text_clean == "1":
            await send_whatsapp_message(
                sender,
                "Reply with your facility/client name and delivery location.\n"
                "Example: Mulago Hospital, Kampala",
            )
            save_session(
                sender,
                {
                    "state": "RFQ_FLOW",
                    "product": session.get("product"),
                    "selected_item": session.get("selected_item"),
                    "quantity": session.get("quantity"),
                },
            )
            return
        if text_clean == "2":
            await send_whatsapp_message(
                sender,
                "Reply with: name | organization | what you need.\n"
                "We will connect you with sales.",
            )
            save_session(
                sender,
                {
                    "state": "TALK_TO_AGENT",
                    "selected_item": session.get("selected_item"),
                    "quantity": session.get("quantity"),
                },
            )
            return
        if text_clean == "3":
            save_session(
                sender,
                {
                    "state": "VIEWING_RESULTS",
                    "product": session.get("product"),
                    "options": session.get("options", []),
                },
            )
            await send_whatsapp_message(sender, "Returning to the supplier offers.")
            return

        await send_whatsapp_message(sender, "Please reply with 1, 2, 3, or 0.")
        return

    if current_state == "RFQ_FLOW":
        selected = session.get("selected_item", {})
        product = session.get("product", {})
        quantity = session.get("quantity", 1)
        organization, delivery_location = _parse_facility_details(text)

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
                notes=f"Selected brand: {selected.get('brand', 'Generic')}",
                currency=currency,
            )
        except Exception as exc:
            log_audit_event(sender, "whatsapp_rfq_failed", {"error": str(exc)})
            await send_whatsapp_message(sender, "We could not submit your quotation request right now. Please try again shortly.")
            save_session(sender, {"state": "MENU"})
            return

        supplier_text = "The supplier has been notified." if supplier_notified else "Our sales team will route it manually."
        await send_whatsapp_message(
            sender,
            f"Quotation request received. RFQ #{rfq_id} has been created.\n"
            f"{supplier_text}\n"
            "A follow-up will be shared with you shortly.",
        )
        save_session(sender, {"state": "MENU"})
        return

    if current_state == "DIRECT_RFQ":
        parsed = _parse_direct_rfq(text)
        if not parsed:
            await send_whatsapp_message(
                sender,
                "Please use this format exactly:\n"
                "item(s) | quantity | facility/client name | delivery location",
            )
            return

        product_name, quantity, organization, delivery_location = parsed
        try:
            rfq_id, _ = await _create_whatsapp_rfq(
                sender=sender,
                product_name=product_name,
                quantity=quantity,
                organization=organization,
                delivery_location=delivery_location,
                source="whatsapp_direct_rfq",
                notes="Generic RFQ from main menu",
                currency=currency,
            )
        except Exception as exc:
            log_audit_event(sender, "direct_whatsapp_rfq_failed", {"error": str(exc)})
            await send_whatsapp_message(sender, "We could not capture your quotation request right now. Please try again.")
            save_session(sender, {"state": "MENU"})
            return

        await send_whatsapp_message(
            sender,
            f"Your quotation request has been logged as RFQ #{rfq_id}.\n"
            "Our team will match it to suppliers and follow up with you.",
        )
        save_session(sender, {"state": "MENU"})
        return

    if current_state == "TALK_TO_AGENT":
        try:
            lead_id = await _capture_sales_lead(sender, text, "whatsapp_sales_handoff")
        except Exception as exc:
            log_audit_event(sender, "sales_lead_failed", {"error": str(exc)})
            await send_whatsapp_message(sender, "We could not hand this off to sales right now. Please try again shortly.")
            save_session(sender, {"state": "MENU"})
            return

        await send_whatsapp_message(
            sender,
            f"Your request has been shared with our sales team. Lead #{lead_id} is now open and someone will reach out shortly.",
        )
        save_session(sender, {"state": "MENU"})
        return

    await send_whatsapp_message(sender, "I did not understand that. Reply 0 for the main menu.")
