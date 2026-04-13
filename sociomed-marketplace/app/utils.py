import requests
from app.config import WHATSAPP_TOKEN, PHONE_NUMBER_ID

# --- WhatsApp भेजना ---
def send_whatsapp_message(to, message):
    url = f"https://graph.facebook.com/v18.0/{PHONE_NUMBER_ID}/messages"

    headers = {
        "Authorization": f"Bearer {WHATSAPP_TOKEN}",
        "Content-Type": "application/json"
    }

    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "text",
        "text": {"body": message}
    }

    requests.post(url, headers=headers, json=payload)


# --- SESSION STORE ---
user_sessions = {}

def save_session(user, data):
    user_sessions[user] = data

def get_session(user):
    return user_sessions.get(user)

def update_session(user, key, value):
    if user not in user_sessions:
        user_sessions[user] = {}
    user_sessions[user][key] = value


# --- Vendor Routing ---
def notify_vendor(vendor_phone, message):
    if vendor_phone:
        send_whatsapp_message(vendor_phone, message)
