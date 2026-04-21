import os
from urllib.parse import urlparse

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
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./sociomed.db")

# Redis — sessions + caching
REDIS_URL = os.getenv("REDIS_URL")
_parsed_redis_url = urlparse(REDIS_URL) if REDIS_URL else None
REDIS_HOST = os.getenv("REDIS_HOST") or (_parsed_redis_url.hostname if _parsed_redis_url else "localhost")
REDIS_PORT = int(os.getenv("REDIS_PORT") or (_parsed_redis_url.port if _parsed_redis_url else 6379))
REDIS_DB = int(os.getenv("REDIS_DB") or ((_parsed_redis_url.path or "/0").lstrip("/") if _parsed_redis_url else 0))

# App settings
CACHE_TTL_SECONDS = int(os.getenv("CACHE_TTL_SECONDS", 300))
SESSION_TTL = int(os.getenv("SESSION_TTL", 1800))
DEFAULT_CURRENCY = os.getenv("DEFAULT_CURRENCY", "UGX")
PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL", "")
SUPPORT_EMAIL = os.getenv("SUPPORT_EMAIL", "sales@sociomed.co")
SALES_AGENT_PHONE = os.getenv("SALES_AGENT_PHONE")
ENABLE_OPEN_DOCS = os.getenv("ENABLE_OPEN_DOCS", "true").lower() == "true"

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
