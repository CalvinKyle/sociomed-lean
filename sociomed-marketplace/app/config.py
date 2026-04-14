import os
from dotenv import load_dotenv

load_dotenv()

# WhatsApp
VERIFY_TOKEN = os.getenv("VERIFY_TOKEN")
WHATSAPP_TOKEN = os.getenv("WHATSAPP_TOKEN")
PHONE_NUMBER_ID = os.getenv("PHONE_NUMBER_ID")
WHATSAPP_APP_SECRET = os.getenv("WHATSAPP_APP_SECRET")

# Google Sheets (still used by sync script)
GOOGLE_CREDS_FILE = os.getenv("GOOGLE_CREDS_FILE", "credentials.json")
SHEET_NAME = os.getenv("SHEET_NAME", "sociomed_db")

# PostgreSQL — core database
DATABASE_URL = os.getenv("DATABASE_URL")

# Redis — sessions + caching
REDIS_HOST = os.getenv("REDIS_HOST")
REDIS_PORT = int(os.getenv("REDIS_PORT", 6379))

# App settings
CACHE_TTL_SECONDS = int(os.getenv("CACHE_TTL_SECONDS", 300))
SESSION_TTL = int(os.getenv("SESSION_TTL", 1800))
DEFAULT_CURRENCY = os.getenv("DEFAULT_CURRENCY", "UGX")

def validate_config():
    missing = []
    required = {
        "VERIFY_TOKEN": VERIFY_TOKEN,
        "WHATSAPP_TOKEN": WHATSAPP_TOKEN,
        "PHONE_NUMBER_ID": PHONE_NUMBER_ID,
        "DATABASE_URL": DATABASE_URL,
        "REDIS_HOST": REDIS_HOST,
    }
    for key, value in required.items():
        if not value:
            missing.append(key)
    if missing:
        raise Exception(f"Missing required env vars: {', '.join(missing)}")
