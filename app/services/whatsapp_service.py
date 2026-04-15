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
from app.services.search import find_product, get_results
from app.schemas.formatter import format_results
from app.core.cache import get_cached_data  # ← New helper we'll add in core/cache.py


def extract_message(body: Dict) -> Optional[Dict]:
    """Safely extract WhatsApp message (now synchronous for webhook)."""
    try:
        return body["entry"][0]["changes"][0]["value"]["messages"][0]
    except (KeyError, IndexError, TypeError):
        return None


async def handle_incoming_message(message: Dict):
    """Main WhatsApp conversation handler — now follows strict v2.3 state machine"""
    text = message["text"]["body"].strip()
    sender = message["from"]
    text_clean = text.lower()

    session = get_session(sender) or {}
    current_state = session.get("state", "MENU")

    # ── STEP 0: Entry Point / Session Timeout → Welcome + Menu
    if not session or current_state == "IDLE":
        welcome = (
            "👋 Welcome to SocioMed Marketplace!\n\n"
            "Your reliable partner for quality medical equipment, consumables and devices in Uganda.\n\n"
            "How can I help you today?\n\n"
            "Reply with a number:\n"
            "1️⃣ Search for products\n"
            "2️⃣ View Featured Products\n"
            "3️⃣ View my Cart\n"
            "4️⃣ My previous PFIs / Orders\n"
            "5️⃣ Talk to a Sales Agent\n"
            "6️⃣ Help / How it works"
        )
        await send_whatsapp_message(sender, welcome)
        save_session(sender, {"state": "MENU"})
        return

    # ── Back / Main Menu command (works at every step)
    if text_clean in ["0", "m", "menu", "back"]:
        await send_whatsapp_message(sender, "Returning to main menu...")
        save_session(sender, {"state": "MENU"})
        return

    # ── STATE MACHINE
    if current_state == "MENU":
        if text_clean == "1":
            await send_whatsapp_message(sender, 
                "Please type the product(s) you are looking for (e.g. Surgical gloves, IV set, Oxygen mask). "
                "You can search one or multiple items separated by commas.")
            update_session(sender, "state", "SEARCHING")
            return
        elif text_clean == "2":
            # TODO: Call featured products logic (we can expand later)
            await send_whatsapp_message(sender, "Featured Products coming soon...")
            save_session(sender, {"state": "MENU"})
            return
        elif text_clean == "3":
            # View Cart
            await send_whatsapp_message(sender, "Cart is empty for now.")
            save_session(sender, {"state": "MENU"})
            return
        elif text_clean == "5":
            await send_whatsapp_message(sender, 
                "Connecting you to a Sales Agent...\nOne of our team members will reply shortly with your full conversation history.")
            save_session(sender, {"state": "MENU"})
            return
        else:
            await send_whatsapp_message(sender, "Please reply with a number 1–6 from the menu.")
            return

    # ── SEARCHING STATE
    elif current_state == "SEARCHING":
        # Simple multiple-product detection
        if "," in text or " and " in text_clean or "+" in text:
            await send_whatsapp_message(sender,
                "I found multiple items. For the fastest response:\n"
                "1 – Request a combined RFQ for all items\n"
                "2 – Search them one by one\n"
                "3 – Talk to a Sales Agent")
            update_session(sender, "state", "RFQ_FLOW")
            return

        # Single product search
        data = get_cached_data()
        product = find_product(text, data.get("products", []), data.get("aliases", []))
        if not product:
            await send_whatsapp_message(sender,
                "Sorry, we couldn’t find that exact product.\n"
                "1 – Try a different search\n"
                "2 – Request RFQ\n"
                "0 – Main menu")
            return

        results = get_results(product["product_id"], data)
        reply, option_map = format_results(product["name"], results)
        save_session(sender, {
            "state": "VIEWING_RESULTS",
            "product": product,
            "options": option_map
        })
        await send_whatsapp_message(sender, reply)
        return

    # ── All other states (VIEWING_RESULTS, SELECTING_PRODUCT, ENTERING_QUANTITY, etc.)
    # will be expanded in the next iteration once you confirm this base is working.
    # For now, we fall back gracefully:
    else:
        await send_whatsapp_message(sender,
            "I didn’t understand that. Please reply with a number from the options or type 0 for main menu.")
        return
