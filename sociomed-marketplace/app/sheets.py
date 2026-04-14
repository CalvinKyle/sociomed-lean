import gspread
import time
from oauth2client.service_account import ServiceAccountCredentials
from app.config import GOOGLE_CREDS_FILE, SHEET_NAME, CACHE_TTL_SECONDS

scope = [
    "https://spreadsheets.google.com/feeds",
    "https://www.googleapis.com/auth/drive"
]

creds = ServiceAccountCredentials.from_json_keyfile_name(GOOGLE_CREDS_FILE, scope)
client = gspread.authorize(creds)

sheet = client.open(SHEET_NAME)

# --- CACHE ---
_cache = {
    "data": None,
    "last_loaded": 0
}


def load_data():
    now = time.time()

    # Return cached data if still valid
    if _cache["data"] and (now - _cache["last_loaded"] < CACHE_TTL_SECONDS):
        return _cache["data"]

    # Reload from Google Sheets
    data = {
        "products": sheet.worksheet("products").get_all_records(),
        "vendors": sheet.worksheet("vendors").get_all_records(),
        "inventory": sheet.worksheet("inventory").get_all_records(),
        "pricing": sheet.worksheet("pricing").get_all_records(),
        "aliases": sheet.worksheet("aliases").get_all_records(),
    }

    _cache["data"] = data
    _cache["last_loaded"] = now

    return data
