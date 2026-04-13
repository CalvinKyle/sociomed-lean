import gspread
from oauth2client.service_account import ServiceAccountCredentials
from app.config import GOOGLE_CREDS_FILE, SHEET_NAME

scope = [
    "https://spreadsheets.google.com/feeds",
    "https://www.googleapis.com/auth/drive"
]

creds = ServiceAccountCredentials.from_json_keyfile_name(GOOGLE_CREDS_FILE, scope)
client = gspread.authorize(creds)

sheet = client.open(SHEET_NAME)

def load_data():
    return {
        "products": sheet.worksheet("products").get_all_records(),
        "vendors": sheet.worksheet("vendors").get_all_records(),
        "inventory": sheet.worksheet("inventory").get_all_records(),
        "pricing": sheet.worksheet("pricing").get_all_records(),
        "aliases": sheet.worksheet("aliases").get_all_records(),
    }
