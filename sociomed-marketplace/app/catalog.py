"""
SocioMed WhatsApp Marketplace Bot
Lean stack: Excel catalog + Flask + Meta Cloud API
No Odoo, no Redis, no Celery required.
"""

import os
import json
import logging
import sqlite3
from datetime import datetime
from flask import Flask, request, jsonify
import requests

from catalog import CatalogEngine
from cart import CartManager
from quote import QuoteGenerator
from messenger import WhatsAppMessenger

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s"
)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# -- Boot components --
catalog = CatalogEngine(os.getenv("CATALOG_PATH", "data/catalog.xlsx"))
cart_mgr = CartManager(db_path=os.getenv("SQLITE_PATH", "data/sessions.db"))
messenger = WhatsAppMessenger(
    token=os.getenv("WHATSAPP_TOKEN"),
    phone_id=os.getenv("WHATSAPP_PHONE_ID"),
    api_version=os.getenv("WHATSAPP_API_VERSION", "v19.0"),
)
quote_gen = QuoteGenerator(
    sheets_creds_json=os.getenv("GOOGLE_SHEETS_CREDS"),   # optional
    quotes_sheet_id=os.getenv("QUOTES_SHEET_ID"),          # optional
)

VERIFY_TOKEN = os.getenv("VERIFY_TOKEN", "sociomed2025")


# ── Webhook verification ────────────────────────────────────────────────────

@app.route("/webhook", methods=["GET"])
def verify():
    if (request.args.get("hub.mode") == "subscribe"
            and request.args.get("hub.verify_token") == VERIFY_TOKEN):
        return request.args.get("hub.challenge"), 200
    return "Forbidden", 403


# ── Incoming messages ───────────────────────────────────────────────────────

@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.get_json(silent=True) or {}
    if data.get("object") != "whatsapp_business_account":
        return jsonify({"status": "ignored"}), 200

    for entry in data.get("entry", []):
        for change in entry.get("changes", []):
            if change.get("field") != "messages":
                continue
            for msg in change.get("value", {}).get("messages", []):
                _handle_message(msg)

    return jsonify({"status": "ok"}), 200


def _handle_message(msg: dict):
    phone = msg.get("from")
    msg_type = msg.get("type")

    # Resolve text from text or interactive (list/button reply)
    if msg_type == "text":
        text = msg["text"]["body"].strip()
    elif msg_type == "interactive":
        itype = msg["interactive"].get("type")
        if itype == "list_reply":
            text = msg["interactive"]["list_reply"]["id"]
        elif itype == "button_reply":
            text = msg["interactive"]["button_reply"]["id"]
        else:
            return
    else:
        return

    logger.info(f"[{phone}] recv: {text[:80]}")

    try:
        response = _route(phone, text)
    except Exception as e:
        logger.error(f"Route error for {phone}: {e}", exc_info=True)
        response = "⚠️ Something went wrong. Please try again or type *help*."

    messenger.send(phone, response)


# ── Router ──────────────────────────────────────────────────────────────────

def _route(phone: str, text: str):
    tl = text.lower().strip()

    # System commands (from interactive list IDs or typed)
    if text.startswith("ADD:"):
        return _cmd_add(phone, text[4:])

    if tl in ("cart", "cmd_cart", "my cart", "view cart"):
        return _cmd_view_cart(phone)

    if tl in ("clear", "cmd_clear", "clear cart", "empty cart"):
        cart_mgr.clear(phone)
        return "🗑️ Cart cleared."

    if tl in ("quote", "cmd_quote", "request quote", "get quote"):
        return _cmd_quote(phone)

    if tl in ("catalog", "cmd_catalog", "price list", "download catalog"):
        return _cmd_catalog()

    if tl in ("support", "cmd_support", "contact", "agent", "human"):
        return _cmd_support()

    if tl in ("hi", "hello", "start", "help", "menu", "hey"):
        return _cmd_greeting()

    if text.startswith("REMOVE:"):
        return _cmd_remove(phone, text[7:])

    # Default: product search
    return _cmd_search(phone, text)


# ── Command handlers ────────────────────────────────────────────────────────

def _cmd_greeting() -> str:
    return (
        "👋 *Welcome to SocioMed Marketplace*\n\n"
        "Your direct source for medical equipment, consumables & health supplies.\n\n"
        "🔍 *Search* — type any product name (e.g. _IV cannula_, _gloves_, _ECG machine_)\n"
        "🛒 *Cart* — type *cart* to view your basket\n"
        "📄 *Quote* — type *quote* to generate a PDF quotation\n"
        "📞 *Support* — type *support* to reach our team\n\n"
        "_Start typing a product to search our catalog_ →"
    )


def _cmd_search(phone: str, query: str):
    results = catalog.search(query, limit=4)

    if not results:
        # Log demand miss for catalog gap analysis
        _log_demand_miss(phone, query)
        return (
            f"❌ No results for *\"{query}\"*.\n\n"
            "Our team has been notified to source this item.\n"
            "Type *support* to speak with an agent directly."
        )

    return _build_product_list(results, query)


def _cmd_add(phone: str, product_id: str):
    product = catalog.get_by_id(product_id)
    if not product:
        return "⚠️ Product not found. Please search again."

    cart_mgr.add(phone, product)
    cart = cart_mgr.get(phone)
    total = sum(i["price_ugx"] * i["qty"] for i in cart)

    response = (
        f"✅ *{product['name']}* added to cart.\n"
        f"   Unit: {product['unit']}  |  UGX {product['price_ugx']:,.0f}\n\n"
        f"🛒 Cart: {len(cart)} item(s) — Total UGX {total:,.0f}\n"
        f"Type *cart* to review or *quote* to generate a quotation."
    )

    # Cross-sell nudge
    related = catalog.get_related(product_id, limit=2)
    if related:
        response += "\n\n💡 *Often ordered with this:*"
        for r in related:
            response += f"\n• {r['name']} — UGX {r['price_ugx']:,.0f}"
        response += "\nSearch by name to add."

    return response


def _cmd_view_cart(phone: str) -> str:
    cart = cart_mgr.get(phone)
    if not cart:
        return "🛒 Your cart is empty.\nSearch for a product to get started."

    lines = ["🛒 *YOUR CART*\n"]
    total = 0
    for i, item in enumerate(cart, 1):
        subtotal = item["price_ugx"] * item["qty"]
        total += subtotal
        lines.append(
            f"{i}. {item['name']}\n"
            f"   Qty: {item['qty']} × UGX {item['price_ugx']:,.0f} = UGX {subtotal:,.0f}"
        )

    lines.append(f"\n*Total: UGX {total:,.0f}*")
    lines.append("\nType *quote* to generate a formal quotation.")
    return "\n".join(lines)


def _cmd_remove(phone: str, index_str: str) -> str:
    try:
        idx = int(index_str) - 1
        removed = cart_mgr.remove(phone, idx)
        return f"✅ Removed *{removed['name']}* from cart."
    except (ValueError, IndexError):
        return "⚠️ Invalid item number. Type *cart* to see your current items."


def _cmd_quote(phone: str):
    cart = cart_mgr.get(phone)
    if not cart:
        return "🛒 Your cart is empty. Search and add products first."

    try:
        quote_ref, pdf_path = quote_gen.generate(phone, cart)
        cart_mgr.clear(phone)

        if pdf_path:
            # Send PDF document
            return {
                "type": "document",
                "document": {
                    "filename": f"SocioMed_{quote_ref}.pdf",
                    "caption": (
                        f"📄 *Quotation {quote_ref}*\n\n"
                        f"Thank you! Our sales team will follow up within 24hrs.\n"
                        f"📞 +256 777 411 435  |  ✉️ info@socio-med.com"
                    ),
                    # In production: upload to WhatsApp media endpoint first
                    # For now we return the text fallback
                },
            }

        return (
            f"📄 *Quotation {quote_ref} Generated*\n\n"
            f"Items: {len(cart)}\n"
            f"Total: UGX {sum(i['price_ugx']*i['qty'] for i in cart):,.0f}\n\n"
            f"Our team will send the full PDF and contact you within 24 hours.\n"
            f"📞 +256 777 411 435"
        )
    except Exception as e:
        logger.error(f"Quote error for {phone}: {e}", exc_info=True)
        return (
            "⚠️ Could not generate quote right now.\n"
            "Please type *support* to reach our team directly."
        )


def _cmd_catalog() -> str:
    catalog_url = os.getenv("CATALOG_PDF_URL", "")
    if catalog_url:
        return {
            "type": "document",
            "document": {
                "link": catalog_url,
                "caption": "📚 SocioMed 2025/26 Product Catalog",
                "filename": "SocioMed_Catalog.pdf",
            },
        }
    return (
        "📚 *SocioMed Catalog*\n\n"
        "Download our full catalog at:\n"
        "🔗 https://socio-med.com/catalog\n\n"
        "Or type a product name to search directly."
    )


def _cmd_support() -> str:
    return (
        "📞 *Contact SocioMed Team*\n\n"
        "📱 WhatsApp/Call: +256 777 411 435\n"
        "✉️  Email: info@socio-med.com\n"
        "🌐 Web: www.socio-med.com\n\n"
        "⏰ Mon–Fri  8:00am – 5:00pm EAT\n\n"
        "A team member will respond within 2 hours during working hours."
    )


# ── WhatsApp interactive list builder ───────────────────────────────────────

def _build_product_list(products: list, query: str) -> dict:
    """Build a WhatsApp interactive list with product rows + action shortcuts."""

    product_rows = []
    for p in products:
        stock_label = {
            "IN_STOCK": "✅ In stock",
            "ON_ORDER": f"📦 ~{p.get('lead_days', 3)}d lead",
            "OUT_OF_STOCK": "❌ Unavailable",
        }.get(p.get("stock_status", ""), "")

        product_rows.append({
            "id": f"ADD:{p['product_id']}",
            "title": p["name"][:24],
            "description": f"{p.get('brand','')[:14]} | {stock_label} | UGX {p['price_ugx']:,.0f}"[:72],
        })

    action_rows = [
        {"id": "cart",        "title": "🛒 View cart",       "description": "See your current basket"},
        {"id": "quote",       "title": "📄 Request quote",   "description": "Generate PDF quotation"},
        {"id": "cmd_catalog", "title": "📚 Get catalog",     "description": "Full price list PDF"},
        {"id": "support",     "title": "📞 Contact us",      "description": "Speak to a team member"},
    ]

    return {
        "type": "interactive",
        "interactive": {
            "type": "list",
            "header": {"type": "text", "text": "SocioMed Search Results"},
            "body": {
                "text": (
                    f"Found {len(products)} result(s) for *\"{query}\"*.\n"
                    "Tap a product to add it to your cart."
                )
            },
            "footer": {"text": "socio-med.com  |  +256 777 411 435"},
            "action": {
                "button": "View Results",
                "sections": [
                    {"title": "Products", "rows": product_rows},
                    {"title": "Quick Actions", "rows": action_rows},
                ],
            },
        },
    }


# ── Demand miss logging ──────────────────────────────────────────────────────

def _log_demand_miss(phone: str, query: str):
    """Log unmatched queries to SQLite for catalog gap analysis."""
    try:
        conn = sqlite3.connect(os.getenv("SQLITE_PATH", "data/sessions.db"))
        conn.execute(
            "CREATE TABLE IF NOT EXISTS demand_misses "
            "(ts TEXT, phone TEXT, query TEXT)"
        )
        conn.execute(
            "INSERT INTO demand_misses VALUES (?, ?, ?)",
            (datetime.utcnow().isoformat(), phone, query),
        )
        conn.commit()
        conn.close()
    except Exception as e:
        logger.warning(f"Demand miss log failed: {e}")


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 5000)), debug=False)
