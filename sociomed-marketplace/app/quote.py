"""
QuoteGenerator — creates PDF quotations and logs to Google Sheets.

PDF is generated with fpdf2 (no external server needed).
Google Sheets logging is optional — set GOOGLE_SHEETS_CREDS env var to enable.
"""

import os
import json
import logging
from datetime import datetime
from typing import List, Tuple, Optional

from fpdf import FPDF

logger = logging.getLogger(__name__)

COMPANY_NAME = os.getenv("COMPANY_NAME", "SocioMed Ltd")
COMPANY_PHONE = os.getenv("COMPANY_PHONE", "+256 777 411 435")
COMPANY_EMAIL = os.getenv("COMPANY_EMAIL", "info@socio-med.com")
COMPANY_WEB = os.getenv("COMPANY_WEB", "www.socio-med.com")
OUTPUT_DIR = os.getenv("QUOTE_OUTPUT_DIR", "data/quotes")


class QuoteGenerator:
    def __init__(self, sheets_creds_json: Optional[str] = None, quotes_sheet_id: Optional[str] = None):
        self.sheets_enabled = False
        self.quotes_sheet_id = quotes_sheet_id
        os.makedirs(OUTPUT_DIR, exist_ok=True)

        if sheets_creds_json and quotes_sheet_id:
            try:
                import gspread
                from google.oauth2.service_account import Credentials
                creds_dict = json.loads(sheets_creds_json)
                creds = Credentials.from_service_account_info(
                    creds_dict,
                    scopes=["https://spreadsheets.google.com/feeds",
                            "https://www.googleapis.com/auth/drive"]
                )
                self._gc = gspread.authorize(creds)
                self.sheets_enabled = True
                logger.info("Google Sheets logging enabled")
            except Exception as e:
                logger.warning(f"Google Sheets init failed (will skip logging): {e}")

    def generate(self, phone: str, cart: List[dict]) -> Tuple[str, Optional[str]]:
        """
        Returns (quote_ref, pdf_path).
        pdf_path is None if PDF generation fails.
        """
        quote_ref = f"SM-{datetime.utcnow().strftime('%Y%m%d')}-{phone[-4:]}"
        total = sum(i["price_ugx"] * i["qty"] for i in cart)

        pdf_path = None
        try:
            pdf_path = self._generate_pdf(quote_ref, phone, cart, total)
        except Exception as e:
            logger.error(f"PDF generation failed: {e}", exc_info=True)

        if self.sheets_enabled:
            try:
                self._log_to_sheets(quote_ref, phone, cart, total)
            except Exception as e:
                logger.warning(f"Sheets logging failed: {e}")

        # Always log locally as fallback
        self._log_local(quote_ref, phone, cart, total)

        return quote_ref, pdf_path

    # ── PDF ────────────────────────────────────────────────────────────────

    def _generate_pdf(self, quote_ref: str, phone: str, cart: List[dict], total: float) -> str:
        pdf = FPDF()
        pdf.add_page()
        pdf.set_margins(15, 15, 15)

        # Header
        pdf.set_fill_color(0, 112, 74)  # SocioMed green
        pdf.rect(0, 0, 210, 28, "F")
        pdf.set_font("Helvetica", "B", 18)
        pdf.set_text_color(255, 255, 255)
        pdf.set_y(8)
        pdf.cell(0, 10, COMPANY_NAME, align="C")

        # Sub-header contact
        pdf.set_font("Helvetica", "", 9)
        pdf.ln(8)
        pdf.cell(0, 5, f"{COMPANY_PHONE}  |  {COMPANY_EMAIL}  |  {COMPANY_WEB}", align="C")

        pdf.ln(12)
        pdf.set_text_color(30, 30, 30)

        # Quote metadata
        pdf.set_font("Helvetica", "B", 13)
        pdf.cell(0, 8, f"QUOTATION  {quote_ref}", ln=True)
        pdf.set_font("Helvetica", "", 10)
        pdf.cell(0, 6, f"Date: {datetime.utcnow().strftime('%d %B %Y')}", ln=True)
        pdf.cell(0, 6, f"Customer: WhatsApp {phone}", ln=True)
        pdf.cell(0, 6, "Valid for: 30 days", ln=True)
        pdf.ln(6)

        # Table header
        col_w = [90, 25, 30, 35]  # Name, Qty, Unit Price, Total
        pdf.set_fill_color(220, 240, 230)
        pdf.set_font("Helvetica", "B", 10)
        for header, w in zip(["Product / Description", "Qty", "Unit Price (UGX)", "Total (UGX)"], col_w):
            pdf.cell(w, 8, header, border=1, fill=True)
        pdf.ln()

        # Table rows
        pdf.set_font("Helvetica", "", 9)
        fill = False
        for item in cart:
            subtotal = item["price_ugx"] * item["qty"]
            pdf.set_fill_color(245, 250, 247) if fill else pdf.set_fill_color(255, 255, 255)
            name_line = f"{item['name']} ({item['unit']})"
            pdf.cell(col_w[0], 7, name_line[:52], border=1, fill=fill)
            pdf.cell(col_w[1], 7, str(item["qty"]), border=1, fill=fill, align="C")
            pdf.cell(col_w[2], 7, f"{item['price_ugx']:,.0f}", border=1, fill=fill, align="R")
            pdf.cell(col_w[3], 7, f"{subtotal:,.0f}", border=1, fill=fill, align="R")
            pdf.ln()
            fill = not fill

        # Total row
        pdf.set_font("Helvetica", "B", 10)
        pdf.set_fill_color(0, 112, 74)
        pdf.set_text_color(255, 255, 255)
        pdf.cell(col_w[0] + col_w[1] + col_w[2], 9, "TOTAL (UGX)", border=1, fill=True, align="R")
        pdf.cell(col_w[3], 9, f"{total:,.0f}", border=1, fill=True, align="R")
        pdf.ln(12)

        # Terms
        pdf.set_text_color(80, 80, 80)
        pdf.set_font("Helvetica", "I", 8)
        pdf.multi_cell(0, 5,
            "Terms: Prices valid for 30 days. Payment: 50% deposit on order, balance on delivery. "
            "Delivery: Kampala 1-2 days; upcountry 3-5 days. All prices exclusive of VAT where applicable."
        )

        # Save
        out_path = os.path.join(OUTPUT_DIR, f"{quote_ref}.pdf")
        pdf.output(out_path)
        logger.info(f"Quote PDF saved: {out_path}")
        return out_path

    # ── Google Sheets ──────────────────────────────────────────────────────

    def _log_to_sheets(self, quote_ref: str, phone: str, cart: List[dict], total: float):
        sh = self._gc.open_by_key(self.quotes_sheet_id)
        try:
            ws = sh.worksheet("quotes_log")
        except Exception:
            ws = sh.add_worksheet(title="quotes_log", rows=1000, cols=8)
            ws.append_row(["quote_id", "timestamp", "phone", "items", "total_ugx", "status"])

        ws.append_row([
            quote_ref,
            datetime.utcnow().isoformat(),
            phone,
            json.dumps([{"name": i["name"], "qty": i["qty"], "price": i["price_ugx"]} for i in cart]),
            total,
            "PENDING",
        ])

    # ── Local fallback log ─────────────────────────────────────────────────

    def _log_local(self, quote_ref: str, phone: str, cart: List[dict], total: float):
        import csv
        log_path = os.path.join(OUTPUT_DIR, "quotes_log.csv")
        write_header = not os.path.exists(log_path)
        with open(log_path, "a", newline="") as f:
            writer = csv.writer(f)
            if write_header:
                writer.writerow(["quote_id", "timestamp", "phone", "items_count", "total_ugx"])
            writer.writerow([quote_ref, datetime.utcnow().isoformat(), phone, len(cart), total])
          
