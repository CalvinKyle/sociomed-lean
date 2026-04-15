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
    """Main WhatsApp conversation handler — FULL v2.3 state machine"""
    text = message["text"]["body"].strip()
    sender = message["from"]
    text_clean = text.lower()

    session = get_session(sender) or {}
    current_state = session.get("state", "MENU")

    # ── GLOBAL BACK / MENU COMMAND (works everywhere)
    if text_clean in ["0", "m", "menu", "back"]:
        await send_whatsapp_message(sender, "Returning to main menu...")
        save_session(sender, {"state": "MENU"})
        return

    # ── STEP 0: Entry Point / Session Timeout
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

    # ── MENU STATE
    if current_state == "MENU":
        if text_clean == "1":
            await send_whatsapp_message(sender,
                "Please type the product(s) you are looking for (e.g. Surgical gloves, IV set, Oxygen mask). "
                "You can search one or multiple items separated by commas.")
            update_session(sender, "state", "SEARCHING")
            return
        elif text_clean == "2":
            await send_whatsapp_message(sender, "Featured Products coming soon...")
            save_session(sender, {"state": "MENU"})
            return
        elif text_clean == "3":
            await send_whatsapp_message(sender, "Your cart is currently empty.")
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
        data = get_cached_data()
        # Simple multiple-product detection
        if "," in text or " and " in text_clean or "+" in text_clean:
            await send_whatsapp_message(sender,
                "I found multiple items. For the fastest response:\n"
                "1 – Request a combined RFQ for all items\n"
                "2 – Search them one by one\n"
                "3 – Talk to a Sales Agent")
            update_session(sender, "state", "RFQ_FLOW")
            return

        # Single product
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

    # ── VIEWING_RESULTS → SELECTING_PRODUCT
    elif current_state == "VIEWING_RESULTS":
        try:
            option_num = int(text_clean)
            options = session.get("options", [])
            if 1 <= option_num <= len(options):
                selected = options[option_num - 1]
                save_session(sender, {
                    "state": "SELECTING_PRODUCT",
                    "selected_item": selected
                })
                await send_whatsapp_message(sender,
                    f"Step 1 of 3 – Quantity\n\n"
                    f"You selected: {selected['brand']} – SKU: {selected.get('sku', 'N/A')} – {selected.get('uom', 'Unit')}\n"
                    f"Stock: {selected.get('stock_qty', 'N/A')} units\n"
                    f"Minimum order: {selected.get('min_qty', 1)} units\n\n"
                    "How many units do you need? (Reply with a number)")
                return
        except ValueError:
            pass
        await send_whatsapp_message(sender, "Please reply with a valid option number.")
        return

    # ── ENTERING_QUANTITY
    elif current_state == "SELECTING_PRODUCT":
        try:
            quantity = int(text_clean)
            selected = session.get("selected_item")
            if quantity < selected.get("min_qty", 1):
                await send_whatsapp_message(sender, f"Minimum order is {selected.get('min_qty', 1)} units. Please enter a higher quantity.")
                return

            save_session(sender, {
                "state": "VIEWING_PRICE",
                "selected_item": selected,
                "quantity": quantity
            })
            await send_whatsapp_message(sender,
                f"Step 2 of 3 – Pricing & Action\n\n"
                f"Default price for {quantity} units: UGX {selected.get('default_price', 'TBD')} each (range pricing)\n\n"
                "Would you like to:\n"
                "1 – Add to Cart\n"
                "2 – Request PFI\n"
                "3 – Back to results\n"
                "0 – Main menu")
            return
        except ValueError:
            await send_whatsapp_message(sender, "Please reply with a number (quantity).")
            return

    # ── VIEWING_PRICE
    elif current_state == "VIEWING_PRICE":
        if text_clean == "1":   # Add to Cart
            cart = session.get("cart", [])
            cart.append({
                "item": session["selected_item"],
                "quantity": session["quantity"]
            })
            save_session(sender, {"state": "CART", "cart": cart})
            await send_whatsapp_message(sender,
                f"✅ Item successfully added to your cart!\n\n"
                f"Thank you. Your cart now has {len(cart)} item(s).\n\n"
                "Reply:\n"
                "1 – View Cart\n"
                "2 – Add another item\n"
                "3 – Proceed to checkout\n"
                "0 – Main menu")
            return
        elif text_clean == "2":   # Request PFI
            await send_whatsapp_message(sender,
                "Step 3 of 3 – PFI Request\n\n"
                "Please reply with your Facility / Client name and Delivery location.")
            update_session(sender, "state", "RFQ_FLOW")
            return
        elif text_clean == "3":
            save_session(sender, {"state": "VIEWING_RESULTS"})  # go back
            await send_whatsapp_message(sender, "Returning to results...")
            return
        else:
            await send_whatsapp_message(sender, "Please choose 1, 2, 3 or 0.")
            return

    # ── CART STATE
    elif current_state == "CART":
        if text_clean == "1":   # View Cart (already shown above)
            await send_whatsapp_message(sender, "Cart view coming in next update.")
            return
        elif text_clean == "3":   # Checkout
            update_session(sender, "state", "CHECKOUT")
            await send_whatsapp_message(sender,
                "Step 3 of 3 – Delivery Details\n\n"
                "Please reply with:\n"
                "• Facility / Client name\n"
                "• Delivery location")
            return
        else:
            await send_whatsapp_message(sender, "Reply 1, 2, 3 or 0.")
            return

    # ── CHECKOUT STATE
    elif current_state == "CHECKOUT":
        # Simple confirmation for now
        await send_whatsapp_message(sender,
            "✅ Order request submitted successfully!\n\n"
            "Thank you. A sales agent will contact you shortly with confirmation.")
        save_session(sender, {"state": "MENU"})
        return

    # ── RFQ_FLOW STATE
    elif current_state == "RFQ_FLOW":
        await send_whatsapp_message(sender,
            "✅ PFI/RFQ request sent successfully!\n\n"
            "Thank you. Your quotation request has been forwarded. You will receive a response soon.")
        save_session(sender, {"state": "MENU"})
        return

    # ── Fallback guardrail
    else:
        await send_whatsapp_message(sender,
            "I didn’t understand that. Please reply with a number from the options or type 0 for main menu.")
