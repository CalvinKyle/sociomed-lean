"""Generate controlled proforma invoices from persisted RFQ price snapshots."""

from __future__ import annotations

import io
from datetime import date, datetime
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfgen.canvas import Canvas
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from app.core.merchant import MerchantConfig, get_merchant_config


PFI_NAVY = colors.HexColor("#1B2A6B")
PFI_TINT = colors.HexColor("#F2F4FA")
PFI_DISCLAIMER = (
    "This proforma is an estimate, not a final invoice, and must be confirmed "
    "against an official invoice once the order is confirmed."
)

_ONES = [
    "",
    "One",
    "Two",
    "Three",
    "Four",
    "Five",
    "Six",
    "Seven",
    "Eight",
    "Nine",
    "Ten",
    "Eleven",
    "Twelve",
    "Thirteen",
    "Fourteen",
    "Fifteen",
    "Sixteen",
    "Seventeen",
    "Eighteen",
    "Nineteen",
]
_TENS = ["", "", "Twenty", "Thirty", "Forty", "Fifty", "Sixty", "Seventy", "Eighty", "Ninety"]
_SCALES = [(1_000_000_000, "Billion"), (1_000_000, "Million"), (1_000, "Thousand")]
_INITIALS_STOP_WORDS = {"and", "limited", "ltd", "smc", "the"}


def _three_digit_words(number: int) -> str:
    parts = []
    if number >= 100:
        parts.append(f"{_ONES[number // 100]} Hundred")
        number %= 100
    if number >= 20:
        tens_word = _TENS[number // 10]
        if number % 10:
            tens_word += f" {_ONES[number % 10]}"
        parts.append(tens_word)
    elif number > 0:
        parts.append(_ONES[number])
    return " ".join(parts)


def amount_in_words(amount: int) -> str:
    """Convert a non-negative whole-currency amount into English words."""
    if amount < 0:
        raise ValueError("amount must be non-negative")
    if amount == 0:
        return "Zero"

    remaining = amount
    words = []
    for value, name in _SCALES:
        if remaining >= value:
            words.append(f"{_three_digit_words(remaining // value)} {name}")
            remaining %= value
    if remaining:
        words.append(_three_digit_words(remaining))
    return " ".join(words)


def _organization_initials(organization: str) -> str:
    initials = []
    for word in organization.split():
        cleaned = "".join(character for character in word if character.isalnum())
        if not cleaned or cleaned.lower() in _INITIALS_STOP_WORDS:
            continue
        initial = cleaned[0].upper()
        if not initials or initials[-1] != initial:
            initials.append(initial)
    return "".join(initials)[:5] or "SM"


def _issue_date(rfq) -> date:
    created_at = rfq.created_at
    if isinstance(created_at, datetime):
        return created_at.date()
    return created_at or date.today()


def resolve_pfi_number(rfq, sequence: int | None = None) -> str:
    """Assign and return a stable organization/date/RFQ-sequence reference."""
    if rfq.pfi_reference:
        return rfq.pfi_reference
    sequence_number = sequence if sequence is not None else rfq.id
    rfq.pfi_reference = (
        f"{_organization_initials(rfq.organization)}/"
        f"{_issue_date(rfq).strftime('%d%m%y')}/{sequence_number:02d}"
    )
    return rfq.pfi_reference


def _draw_page_footer(canvas: Canvas, document: SimpleDocTemplate) -> None:
    canvas.saveState()
    canvas.setStrokeColor(PFI_NAVY)
    canvas.setLineWidth(0.5)
    canvas.line(14 * mm, 8 * mm, A4[0] - 14 * mm, 8 * mm)
    canvas.setFillColor(colors.HexColor("#555555"))
    canvas.setFont("Helvetica", 7.5)
    canvas.drawString(14 * mm, 4.5 * mm, f"PFI {document.pfi_reference}")
    canvas.drawRightString(A4[0] - 14 * mm, 4.5 * mm, f"Page {canvas.getPageNumber()}")
    canvas.restoreState()


def _merchant_address_lines(merchant: MerchantConfig) -> list[str]:
    lines = list(merchant.address_lines)
    lines.extend(f"Phone: {phone}" for phone in merchant.phone_lines)
    lines.append(f"Email: {merchant.email}")
    if merchant.website:
        lines.append(f"Website: {merchant.website}")
    if merchant.tax_id:
        lines.append(f"Tax ID: {merchant.tax_id}")
    return lines


def _bank_details(merchant: MerchantConfig) -> list[str]:
    details = [
        f"Bank: {merchant.bank_name}",
        f"Account name: {merchant.bank_account_name}",
        f"Account number: {merchant.bank_account_number}",
    ]
    if merchant.bank_branch:
        details.append(f"Branch: {merchant.bank_branch}")
    if merchant.bank_swift:
        details.append(f"SWIFT/code: {merchant.bank_swift}")
    return details


def _commercial_terms(merchant: MerchantConfig, line_items: list) -> list[tuple[str, str]]:
    item_types = {str(getattr(item, "item_type", "generic") or "generic").lower() for item in line_items}
    rows = [
        ("Delivery:", merchant.delivery_terms),
        ("Quote Validity:", f"{merchant.validity_days} Days"),
        ("Payment Terms:", merchant.payment_terms),
        ("VAT/Tax:", merchant.vat_wording),
    ]
    if "equipment" in item_types:
        if merchant.equipment_installation:
            rows.append(("Equipment Installation:", merchant.equipment_installation))
        if merchant.equipment_warranty:
            rows.append(("Equipment Warranty:", merchant.equipment_warranty))
    if item_types == {"consumable"} and merchant.consumables_warranty:
        rows.append(("Consumables Warranty:", merchant.consumables_warranty))
    if merchant.technical_support and "equipment" in item_types:
        rows.append(("Technical Support:", merchant.technical_support))
    return [(label, value) for label, value in rows if value]


def generate_pfi_pdf(
    rfq,
    line_items: list,
    merchant_config: MerchantConfig | None = None,
) -> bytes:
    """Build a complete PFI from stable line snapshots and validated configuration."""
    if not line_items:
        raise ValueError("at least one line item is required")
    merchant = merchant_config or get_merchant_config()
    if not merchant.is_complete:
        missing = ", ".join((*merchant.missing_required_fields, *merchant.configuration_errors))
        raise ValueError(f"merchant configuration is incomplete: {missing}")

    currency = str(rfq.currency or "").strip().upper()
    if not currency:
        raise ValueError("RFQ currency is required")
    for item in line_items:
        if not isinstance(item.quantity, int) or item.quantity <= 0:
            raise ValueError("every PFI line requires a valid quantity")
        if not str(item.uom or "").strip():
            raise ValueError("every PFI line requires a UoM")
        if not isinstance(item.unit_price, int) or item.unit_price <= 0:
            raise ValueError("every PFI line requires a persisted unit price")
        if not isinstance(item.line_total, int) or item.line_total != item.unit_price * item.quantity:
            raise ValueError("every PFI line requires a valid persisted line total")
    styles = getSampleStyleSheet()
    address_style = ParagraphStyle(
        "address",
        parent=styles["Normal"],
        alignment=TA_RIGHT,
        fontSize=8.5,
        leading=11,
    )
    name_style = ParagraphStyle(
        "zelus_name",
        parent=styles["Normal"],
        fontSize=18,
        textColor=PFI_NAVY,
        leading=22,
    )
    tagline_style = ParagraphStyle(
        "tagline",
        parent=styles["Normal"],
        fontSize=9,
        textColor=PFI_NAVY,
        leading=12,
    )
    cell_style = ParagraphStyle("cell", parent=styles["Normal"], fontSize=8.5, leading=10.5)

    buffer = io.BytesIO()
    document = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        topMargin=11 * mm,
        bottomMargin=13 * mm,
        leftMargin=14 * mm,
        rightMargin=14 * mm,
    )
    document.pfi_reference = rfq.pfi_reference or "-"
    story = []

    letterhead = Table(
        [
            [
                Paragraph(f"<b>{escape(merchant.display_name)}</b>", name_style),
                Paragraph(
                    "<br/>".join(escape(line) for line in _merchant_address_lines(merchant)),
                    address_style,
                ),
            ],
            [
                Paragraph(
                    "<br/>".join(
                        filter(
                            None,
                            (
                                f"<i>{escape(merchant.tagline)}</i>" if merchant.tagline else "",
                                f"Legal seller: {escape(merchant.legal_name)}",
                            ),
                        )
                    ),
                    tagline_style,
                ),
                "",
            ],
        ],
        colWidths=[90 * mm, 86 * mm],
    )
    letterhead.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("SPAN", (1, 0), (1, 1)),
                ("LINEBELOW", (0, 1), (-1, 1), 1.2, PFI_NAVY),
                ("BOTTOMPADDING", (0, 1), (-1, 1), 8),
                ("TOPPADDING", (0, 0), (-1, -1), 0),
            ]
        )
    )
    story.extend([letterhead, Spacer(1, 4 * mm)])

    issue_date = _issue_date(rfq)
    buyer_block = Paragraph(
        "To:<br/>The Procurement Department"
        f"<br/><b>{escape(rfq.organization)}</b>"
        f"<br/>Attn: {escape(rfq.buyer_name)}",
        cell_style,
    )
    metadata_table = Table(
        [
            ["PFI NUMBER:", rfq.pfi_reference or "-"],
            ["Date:", issue_date.strftime("%d %b %Y")],
            ["Quotation Validity:", f"{merchant.validity_days} Days"],
            ["RFQ No:", f"#{rfq.id}"],
        ],
        colWidths=[38 * mm, 48 * mm],
    )
    metadata_table.setStyle(
        TableStyle(
            [
                ("GRID", (0, 0), (-1, -1), 0.5, colors.black),
                ("FONTSIZE", (0, 0), (-1, -1), 9),
                ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("BACKGROUND", (0, 0), (0, -1), PFI_TINT),
            ]
        )
    )
    metadata_block = Table(
        [
            [
                Paragraph(
                    "<b>PROFORMA INVOICE</b>",
                    ParagraphStyle("pfi_title", parent=cell_style, alignment=TA_RIGHT, fontSize=11),
                )
            ],
            [metadata_table],
        ],
        colWidths=[86 * mm],
    )
    metadata_block.setStyle(
        TableStyle(
            [
                ("ALIGN", (0, 0), (0, 0), "RIGHT"),
                ("BOTTOMPADDING", (0, 0), (0, 0), 4),
            ]
        )
    )
    header_table = Table([[buyer_block, metadata_block]], colWidths=[90 * mm, 86 * mm])
    header_table.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("BOX", (0, 0), (0, 0), 0.5, colors.black),
                ("LEFTPADDING", (0, 0), (0, 0), 6),
                ("TOPPADDING", (0, 0), (0, 0), 6),
            ]
        )
    )
    story.extend([header_table, Spacer(1, 4 * mm)])

    rows = [["S.No", "Item Description", "Qty", "Unit Price", "Total Price"]]
    grand_total = 0
    for index, item in enumerate(line_items, start=1):
        line_total = item.line_total
        unit_price_text = f"{currency} {item.unit_price:,}"
        total_price_text = f"{currency} {line_total:,}"
        grand_total += line_total

        rows.append(
            [
                str(index),
                Paragraph(escape(item.product_name), cell_style),
                str(item.quantity),
                unit_price_text,
                total_price_text,
            ]
        )

    items_table = Table(
        rows,
        colWidths=[12 * mm, 86 * mm, 16 * mm, 32 * mm, 34 * mm],
        repeatRows=1,
    )
    items_table.setStyle(
        TableStyle(
            [
                ("GRID", (0, 0), (-1, -1), 0.5, colors.black),
                ("BACKGROUND", (0, 0), (-1, 0), PFI_NAVY),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 8.5),
                ("ALIGN", (0, 0), (0, -1), "CENTER"),
                ("ALIGN", (2, 0), (2, -1), "CENTER"),
                ("ALIGN", (3, 0), (4, -1), "RIGHT"),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, PFI_TINT]),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]
        )
    )
    story.append(items_table)

    total_table = Table(
        [["TOTAL", currency, f"{grand_total:,}"]],
        colWidths=[68 * mm, 20 * mm, 88 * mm],
    )
    total_table.setStyle(
        TableStyle(
            [
                ("GRID", (0, 0), (-1, -1), 0.5, colors.black),
                ("FONTNAME", (0, 0), (-1, -1), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 11),
                ("ALIGN", (0, 0), (0, 0), "CENTER"),
                ("ALIGN", (2, 0), (2, 0), "RIGHT"),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ]
        )
    )
    story.append(total_table)

    amount_note = f"<b>Amount in words:</b> {amount_in_words(grand_total)} Only"
    amount_style = ParagraphStyle(
        "amount_words",
        parent=styles["Normal"],
        fontSize=9.5,
        spaceBefore=5,
        spaceAfter=6,
    )
    story.append(Paragraph(amount_note, amount_style))
    story.append(
        Paragraph(
            escape(PFI_DISCLAIMER),
            ParagraphStyle(
                "pfi_disclaimer",
                parent=styles["Normal"],
                fontSize=8.5,
                leading=11,
                textColor=colors.HexColor("#444444"),
                spaceAfter=6,
            ),
        )
    )

    terms_rows = _commercial_terms(merchant, line_items)
    terms_table = Table(
        [
            [
                Paragraph(f"<b>{escape(label)}</b>", cell_style),
                Paragraph(escape(str(value)), cell_style),
            ]
            for label, value in terms_rows
        ],
        colWidths=[32 * mm, 58 * mm],
    )
    terms_table.setStyle(
        TableStyle(
            [
                ("GRID", (0, 0), (-1, -1), 0.5, colors.black),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]
        )
    )
    bank_table = Table(
        [["BANK DETAILS"]] + [[line] for line in _bank_details(merchant)],
        colWidths=[86 * mm],
    )
    bank_table.setStyle(
        TableStyle(
            [
                ("GRID", (0, 0), (-1, -1), 0.5, colors.black),
                ("FONTNAME", (0, 0), (0, 0), "Helvetica-Bold"),
                ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("FONTSIZE", (0, 0), (-1, -1), 9.5),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]
        )
    )
    terms_and_bank = Table([[terms_table, bank_table]], colWidths=[92 * mm, 88 * mm])
    terms_and_bank.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP")]))
    story.extend([Spacer(1, 3 * mm), terms_and_bank, Spacer(1, 4 * mm)])

    story.append(
        Paragraph(
            "For further information please do not hesitate to contact the undersigned.<br/>"
            "We look forward to your favorable response and assure you the best of our services.",
            styles["Normal"],
        )
    )
    story.extend([Spacer(1, 3 * mm), Paragraph("Thank you for your business!", styles["Normal"])])

    document.build(story, onFirstPage=_draw_page_footer, onLaterPages=_draw_page_footer)
    return buffer.getvalue()
