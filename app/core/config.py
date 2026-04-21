import os
from urllib.parse import urlparse

from dotenv import load_dotenv

load_dotenv(".env")
load_dotenv(".env.local", override=True)

APP_ENV = os.getenv("APP_ENV", "development").lower()

# WhatsApp
VERIFY_TOKEN = os.getenv("VERIFY_TOKEN")
WHATSAPP_TOKEN = os.getenv("WHATSAPP_TOKEN")
PHONE_NUMBER_ID = os.getenv("PHONE_NUMBER_ID")
WHATSAPP_APP_SECRET = os.getenv("WHATSAPP_APP_SECRET")

# Google Sheets (still used by sync script)
GOOGLE_CREDS_FILE = os.getenv("GOOGLE_CREDS_FILE", ".secrets/google-service-account.json")
GOOGLE_CREDS_JSON = os.getenv("GOOGLE_CREDS_JSON")
SHEET_NAME = os.getenv("SHEET_NAME", "sociomed_db")

# PostgreSQL — core database
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./sociomed.db")

# Redis — sessions + caching
REDIS_URL = os.getenv("REDIS_URL")
_parsed_redis_url = urlparse(REDIS_URL) if REDIS_URL else None
REDIS_HOST = os.getenv("REDIS_HOST") or (_parsed_redis_url.hostname if _parsed_redis_url else "localhost")
REDIS_PORT = int(os.getenv("REDIS_PORT") or (_parsed_redis_url.port if _parsed_redis_url else 6379))
_default_redis_db = 0
if _parsed_redis_url and _parsed_redis_url.path and _parsed_redis_url.path != "/":
    _default_redis_db = int(_parsed_redis_url.path.lstrip("/"))
REDIS_DB = int(os.getenv("REDIS_DB", str(_default_redis_db)))

# App settings
CACHE_TTL_SECONDS = int(os.getenv("CACHE_TTL_SECONDS", 300))
SESSION_TTL = int(os.getenv("SESSION_TTL", 1800))
DEFAULT_CURRENCY = os.getenv("DEFAULT_CURRENCY", "UGX")
PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL", "")
SUPPORT_EMAIL = os.getenv("SUPPORT_EMAIL", "sales@sociomed.co")
SALES_AGENT_PHONE = os.getenv("SALES_AGENT_PHONE")
ENABLE_OPEN_DOCS = os.getenv("ENABLE_OPEN_DOCS", "true").lower() == "true"

def build_redis_url(db: int | None = None) -> str:
    target_db = REDIS_DB if db is None else db
    if _parsed_redis_url:
        return _parsed_redis_url._replace(path=f"/{target_db}").geturl()
    return f"redis://{REDIS_HOST}:{REDIS_PORT}/{target_db}"

def validate_config():
    missing = []
    required = {
        "DATABASE_URL": DATABASE_URL,
        "REDIS_URL_OR_HOST": REDIS_URL or REDIS_HOST,
    }
    if APP_ENV == "production":
        required.update(
            {
                "VERIFY_TOKEN": VERIFY_TOKEN,
                "WHATSAPP_TOKEN": WHATSAPP_TOKEN,
                "PHONE_NUMBER_ID": PHONE_NUMBER_ID,
                "WHATSAPP_APP_SECRET": WHATSAPP_APP_SECRET,
                "SALES_AGENT_PHONE": SALES_AGENT_PHONE,
                "PUBLIC_BASE_URL": PUBLIC_BASE_URL,
            }
        )
    for key, value in required.items():
        if not value:
            missing.append(key)
    if missing:
        raise Exception(f"Missing required env vars: {', '.join(missing)}")
