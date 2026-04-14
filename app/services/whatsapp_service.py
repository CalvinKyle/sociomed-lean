from typing import Dict, Any, Optional
import json

# ── Core imports ──
from app.core.config import VERIFY_TOKEN, PHONE_NUMBER_ID, WHATSAPP_TOKEN
from app.core.utils import (
    send_whatsapp_message,
    save_session,
    get_session,
    update_session,
    notify_vendor,
    log_audit_event,
)
from app.services.search import find_product, get_results, format_results
from app.core.cache import get_cached_data  # ← New helper we'll add in core/cache.py


def extract_message(body: Dict) -> Optional[Dict]:
    """Safely extract WhatsApp message (now synchronous for webhook)."""
    try:
        return body["entry"][0]["changes"][0]["value"]["messages"][0]
    except (KeyError, IndexError, TypeError):
        return None


async def handle_incoming_message(message: Dict):
    """Main WhatsApp conversation handler (runs in Celery background task)."""
    text = message["text"]["body"].strip()
    sender = message["from"]

    text_clean = text.lower()
    session = get_session(sender)

    # ── PFI Flow ──
    if session and text_clean == "1":
        update_session(sender, "stage", "pfi_name")
        await send_whatsapp_message(sender, "Enter facility name:")
        return

    if session and session.get("stage") == "pfi_name":
        update_session(sender, "facility_name", text)
        update_session(sender, "stage", "pfi_location")
        await send_whatsapp_message(sender, "Enter delivery location:")
        return

    if session and session.get("stage") == "pfi_location":
        update_session(sender, "location", text)
        update_session(sender, "stage", "pfi_quantity")
        await send_whatsapp_message(sender, "Enter required quantity:")
        return

    if session and session.get("stage") == "pfi_quantity":
        update_session(sender, "quantity", text)
        summary = (
            "*PFI REQUEST RECEIVED*\n\n"
            f"Product: {session['product']['name']}\n"
            f"Quantity: {text}\n"
            f"Facility: {session['facility_name']}\n"
            f"Location: {session['location']}\n\n"
            "Thank you! Your request has been sent to the supplier."
        )
        await send_whatsapp_message(sender, summary)

        # Notify the best vendor
        first_option = session["options"][0]
        first_vendor = first_option["items"][0]
        await notify_vendor(first_vendor.get("vendor_phone"), summary)
        return

    # ── Quick reply: Show best price (Option 2) ──
    if session and text_clean == "2":
        best_option = min(
            session["options"],
            key=lambda o: min(
                tier["unit_price"]
                for item in o.get("items", [])
                for tier in item.get("pricing", [])
            )
        )
        await send_whatsapp_message(
            sender, f"✅ Best option: {best_option.get('brand')} (Option {best_option.get('option')})"
        )
        return

    # ── Normal product search (now uses cached data) ──
    data = get_cached_data()   # ← This is the important fix

    product = find_product(text, data.get("products", []), data.get("aliases", []))

    if not product:
        await send_whatsapp_message(sender, "❌ Product not found. Try another name or spelling.")
        log_audit_event(sender, "product_not_found", {"query": text})
        return

    # Get pricing & inventory options
    results = get_results(product["product_id"], data)
    reply, option_map = format_results(product["name"], results)

    # Save session for future PFI flow
    save_session(sender, {
        "product": product,
        "options": option_map
    })

    await send_whatsapp_message(sender, reply)
    log_audit_event(sender, "product_searched", {"product": product["name"]})
