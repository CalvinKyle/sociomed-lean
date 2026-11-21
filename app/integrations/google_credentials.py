"""Lazy, shared Sheets authentication; importing this module performs no I/O."""
def sheets_client():
    import json
    import gspread
    from google.oauth2.service_account import Credentials
    from app.core.config import GOOGLE_CREDS_FILE, GOOGLE_CREDS_JSON
    scopes = ['https://www.googleapis.com/auth/spreadsheets', 'https://www.googleapis.com/auth/drive.readonly']
    credentials = (Credentials.from_service_account_info(json.loads(GOOGLE_CREDS_JSON), scopes=scopes)
                   if GOOGLE_CREDS_JSON else Credentials.from_service_account_file(GOOGLE_CREDS_FILE, scopes=scopes))
    return gspread.authorize(credentials)
