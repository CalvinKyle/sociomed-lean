import requests
import time
from app.config import WHATSAPP_TOKEN, PHONE_NUMBER_ID

# -----------------------------
# WhatsApp إرسال
# -----------------------------
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

    for attempt in range(3):
        try:
            res = requests.post(url, headers=headers, json=payload)

            if res.status_code == 200:
                return True

            print("WhatsApp API error:", res.text)

        except Exception as e:
            print("Send error:", e)

        time.sleep(1)

    return False


# -----------------------------
# SESSION STORE (with expiry)
# -----------------------------
user_sessions = {}
SESSION_TTL = 1800  # 30 minutes


def save_session(user, data):
    user_sessions[user] = {
        "data": data,
        "timestamp": time.time()
    }


def get_session(user):
    session = user_sessions.get(user)

    if not session:
        return None

    if time.time() - session["timestamp"] > SESSION_TTL:
        del user_sessions[user]
        return None

    return session["data"]


def update_session(user, key, value):
    if user not in user_sessions:
        user_sessions[user] = {"data": {}, "timestamp": time.time()}

    user_sessions[user]["data"][key] = value
    user_sessions[user]["timestamp"] = time.time()


# -----------------------------
# Vendor Notification
# -----------------------------
def notify_vendor(vendor_phone, message):
    if vendor_phone:
        send_whatsapp_message(vendor_phone, message)
