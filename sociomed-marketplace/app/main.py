from fastapi import FastAPI, Request
from app.config import VERIFY_TOKEN
from app.sheets import load_data
from app.search import find_product, get_results
from app.formatter import format_results
from app.utils import (
    send_whatsapp_message,
    save_session,
    get_session,
    update_session,
    notify_vendor
)

app = FastAPI()


@app.get("/webhook")
def verify(mode: str = None, token: str = None, challenge: str = None):
    if token == VERIFY_TOKEN:
        return int(challenge)
    return "Verification failed"


@app.post("/webhook")
async def webhook(req: Request):
    body = await req.json()

    try:
        message = body["entry"][0]["changes"][0]["value"]["messages"][0]
        text = message["text"]["body"]
        sender = message["from"]

        text_clean = text.strip().lower()
        session = get_session(sender)

        # -----------------------------
        # PFI FLOW
        # -----------------------------

        if session and text_clean == "1":
            update_session(sender, "stage", "pfi_name")
            send_whatsapp_message(sender, "Enter facility name:")
            return {"status": "ok"}

        if session and session.get("stage") == "pfi_name":
            update_session(sender, "facility_name", text)
            update_session(sender, "stage", "pfi_location")
            send_whatsapp_message(sender, "Enter delivery location:")
            return {"status": "ok"}

        if session and session.get("stage") == "pfi_location":
            update_session(sender, "location", text)
            update_session(sender, "stage", "pfi_quantity")
            send_whatsapp_message(sender, "Enter required quantity:")
            return {"status": "ok"}

        if session and session.get("stage") == "pfi_quantity":
            update_session(sender, "quantity", text)

            summary = (
                "*PFI REQUEST*\n\n"
                f"Product: {session['product']['name']}\n"
                f"Quantity: {session['quantity']}\n"
                f"Facility: {session['facility_name']}\n"
                f"Location: {session['location']}\n"
            )

            send_whatsapp_message(sender, summary + "\nSubmitted to supplier.")

            # route to first vendor (MVP logic)
            first_option = session["options"][0]
            first_vendor = first_option["items"][0]

            notify_vendor(first_vendor["vendor_phone"], summary)

            return {"status": "ok"}

        # -----------------------------
        # RECOMMENDATION
        # -----------------------------

        if session and text_clean == "2":
            best_option = min(
                session["options"],
                key=lambda o: min(
                    tier["unit_price"]
                    for item in o["items"]
                    for tier in item["pricing"]
                )
            )

            send_whatsapp_message(
                sender,
                f"Best option: {best_option['brand']} (Option {best_option['option']})"
            )
            return {"status": "ok"}

        # -----------------------------
        # NEW SEARCH
        # -----------------------------

        data = load_data()

        product = find_product(text, data["products"], data["aliases"])

        if not product:
            send_whatsapp_message(sender, "Product not found. Try another name.")
            return {"status": "ok"}

        results = get_results(product["product_id"], data)

        reply, option_map = format_results(product["name"], results)

        save_session(sender, {
            "product": product,
            "options": option_map
        })

        send_whatsapp_message(sender, reply)

    except Exception as e:
        print("Error:", e)

    return {"status": "ok"}
