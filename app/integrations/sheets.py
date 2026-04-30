import json
import gspread
from google.oauth2.service_account import Credentials
from app.core.config import GOOGLE_CREDS_FILE, GOOGLE_CREDS_JSON, SHEET_NAME

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive.readonly"
]

if GOOGLE_CREDS_JSON:
    creds = Credentials.from_service_account_info(json.loads(GOOGLE_CREDS_JSON), scopes=SCOPES)
else:
    creds = Credentials.from_service_account_file(GOOGLE_CREDS_FILE, scopes=SCOPES)
client = gspread.authorize(creds)
sheet = client.open(SHEET_NAME)


def load_data():
    return {
        "products":  sheet.worksheet("products").get_all_records(),
        "vendors":   sheet.worksheet("vendors").get_all_records(),
        "inventory": sheet.worksheet("inventory").get_all_records(),
        "pricing":   sheet.worksheet("pricing").get_all_records(),
        "aliases":   sheet.worksheet("aliases").get_all_records(),
    }
