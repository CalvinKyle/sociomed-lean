from datetime import datetime
from types import SimpleNamespace

from app.services.pfi_generator import (
    DEFAULT_TERMS,
    PFI_DISCLAIMER,
    amount_in_words,
    generate_pfi_pdf,
    resolve_pfi_number,
)


def _rfq():
    return SimpleNamespace(
        id=1,
        buyer_name="Dr. Ali",
        organization="Key Care Mobile Medical Services",
        currency="UGX",
        pfi_reference=None,
        created_at=datetime(2025, 2, 17, 9, 0, 0),
    )


def test_amount_in_words_matches_sample_total():
    assert amount_in_words(225_812_500) == (
        "Two Hundred Twenty Five Million Eight Hundred Twelve Thousand Five Hundred"
    )


def test_default_payment_terms_are_cash_on_delivery():
    assert DEFAULT_TERMS["payment_terms"] == "Cash on Delivery"


def test_pfi_disclaimer_states_that_the_proforma_is_not_a_final_invoice():
    assert "not a final invoice" in PFI_DISCLAIMER
    assert "official invoice" in PFI_DISCLAIMER


def test_resolve_pfi_number_uses_organization_initials_and_is_idempotent():
    rfq = _rfq()

    assert resolve_pfi_number(rfq) == "KCMS/170225/01"
    assert resolve_pfi_number(rfq, sequence=99) == "KCMS/170225/01"


def test_generate_pfi_pdf_handles_priced_and_unpriced_lines():
    rfq = _rfq()
    resolve_pfi_number(rfq)
    items = [
        SimpleNamespace(
            product_name="Patient Monitor",
            quantity=1,
            unit_price=225_812_500,
            line_total=225_812_500,
            vendor_name="Zelus Life",
        ),
        SimpleNamespace(
            product_name="Specialist Accessory",
            quantity=2,
            unit_price=None,
            line_total=None,
            vendor_name=None,
        ),
    ]

    pdf_bytes = generate_pfi_pdf(rfq, items)

    assert isinstance(pdf_bytes, bytes)
    assert pdf_bytes.startswith(b"%PDF")
    assert len(pdf_bytes) > 1_000
