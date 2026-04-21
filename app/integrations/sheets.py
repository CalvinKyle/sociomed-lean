# app/integrations/sheets.py  —  FULL FILE REPLACEMENT

import gspread
import time
from google.oauth2.service_account import Credentials
from app.core.config import GOOGLE_CREDS_FILE, SHEET_NAME, CACHE_TTL_SECONDS

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive.readonly"
]

creds = Credentials.from_service_account_file(GOOGLE_CREDS_FILE, scopes=SCOPES)
client = gspread.authorize(creds)
sheet = client.open(SHEET_NAME)

_cache = {"data": None, "last_loaded": 0}


def load_data():
    now = time.time()
    if _cache["data"] and (now - _cache["last_loaded"] < CACHE_TTL_SECONDS):
        return _cache["data"]

    data = {
        "products":  sheet.worksheet("products").get_all_records(),
        "vendors":   sheet.worksheet("vendors").get_all_records(),
        "inventory": sheet.worksheet("inventory").get_all_records(),
        "pricing":   sheet.worksheet("pricing").get_all_records(),
        "aliases":   sheet.worksheet("aliases").get_all_records(),
    }

    _cache["data"] = data
    _cache["last_loaded"] = now
    return data
