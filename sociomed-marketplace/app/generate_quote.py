from fpdf import FPDF
import os
from datetime import datetime

class QuotePDF(FPDF):
    def header(self):
        self.set_font("helvetica", "B", 20)
        self.cell(0, 10, "SocioMed Quote", align="C", new_x="LMARGIN", new_y="NEXT")
        self.ln(10)

    def footer(self):
        self.set_y(-15)
        self.set_font("helvetica", "I", 8)
        self.cell(0, 10, f"Page {self.page_no()}", align="C")

def create_quote(user_name, items):
    """
    items: list of dicts {'name': str, 'price': float, 'qty': int}
    """
    pdf = QuotePDF()
    pdf.add_page()
    pdf.set_font("helvetica", size=12)
    
    # Customer Info
    pdf.cell(0, 10, f"Date: {datetime.now().strftime('%Y-%m-%d')}", new_x="LMARGIN", new_y="NEXT")
    pdf.cell(0, 10, f"Customer: {user_name}", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(10)
    
    # Table Header
    pdf.set_font("helvetica", "B", 12)
    pdf.cell(80, 10, "Item Description", border=1)
    pdf.cell(30, 10, "Price", border=1)
    pdf.cell(30, 10, "Qty", border=1)
    pdf.cell(40, 10, "Total", border=1, new_x="LMARGIN", new_y="NEXT")
    
    # Table Body
    pdf.set_font("helvetica", size=12)
    grand_total = 0
    
    for item in items:
        total = item['price'] * item['qty']
        grand_total += total
        
        pdf.cell(80, 10, item['name'][:35], border=1) # Truncate for formatting
        pdf.cell(30, 10, f"{item['price']:,}", border=1)
        pdf.cell(30, 10, str(item['qty']), border=1)
        pdf.cell(40, 10, f"{total:,}", border=1, new_x="LMARGIN", new_y="NEXT")
        
    pdf.ln(5)
    pdf.set_font("helvetica", "B", 14)
    pdf.cell(0, 10, f"Grand Total: UGX {grand_total:,}", align="R")
    
    filename = f"quote_{int(datetime.now().timestamp())}.pdf"
    path = os.path.join("/app/data/outputs", filename)
    pdf.output(path)
    return path
