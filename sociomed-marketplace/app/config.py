import os
from dotenv import load_dotenv

# Load environment variables from .env (local dev)
load_dotenv()


# -----------------------------
# WhatsApp / Meta API Config
# -----------------------------
VERIFY_TOKEN = os.getenv("VERIFY_TOKEN")
WHATSAPP_TOKEN = os.getenv("WHATSAPP_TOKEN")
PHONE_NUMBER_ID = os.getenv("PHONE_NUMBER_ID")


# -----------------------------
# Google Sheets Config
# -----------------------------
GOOGLE_CREDS_FILE = os.getenv("GOOGLE_CREDS_FILE", "credentials.json")
SHEET_NAME = os.getenv("SHEET_NAME", "sociomed_db")


# -----------------------------
# App Behavior Config
# -----------------------------
CACHE_TTL_SECONDS = int(os.getenv("CACHE_TTL_SECONDS", 300))  # future caching
DEFAULT_CURRENCY = os.getenv("DEFAULT_CURRENCY", "UGX")


# -----------------------------
# Validation (Fail Fast)
# -----------------------------
def validate_config():
    missing = []

    required_vars = {
        "VERIFY_TOKEN": VERIFY_TOKEN,
        "WHATSAPP_TOKEN": WHATSAPP_TOKEN,
        "PHONE_NUMBER_ID": PHONE_NUMBER_ID,
    }

    for key, value in required_vars.items():
        if not value:
            missing.append(key)

    if missing:
        raise Exception(f"Missing required environment variables: {', '.join(missing)}")
