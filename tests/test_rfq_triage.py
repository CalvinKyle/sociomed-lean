from app.services.rfq_triage import (
    format_ambiguous_match_message,
    is_bulk_request,
    is_complex_bulk_request,
    parse_direct_rfq_message,
    split_requested_items,
)


def test_split_requested_items_detects_procurement_lists():
    items = split_requested_items("gloves x10, catheters x5 and IV sets x20")

    assert items == ["gloves x10", "catheters x5", "IV sets x20"]
    assert is_bulk_request("gloves x10, catheters x5")
    assert is_complex_bulk_request("a, b, c, d")


def test_parse_direct_rfq_message_keeps_single_item_rfq_specific():
    payload = parse_direct_rfq_message("surgical gloves | 10 | Mulago Hospital | Kampala")

    assert payload is not None
    assert payload.product_name == "surgical gloves"
    assert payload.quantity == 10
    assert payload.source == "whatsapp_direct_rfq"
    assert payload.is_bulk is False


def test_parse_direct_rfq_message_routes_bulk_lists_to_manual_triage():
    payload = parse_direct_rfq_message("gloves x10, catheters x5, IV sets x20 | Mulago Hospital | Kampala")

    assert payload is not None
    assert payload.product_name == "Bulk RFQ: gloves x10, catheters x5, IV sets x20"
    assert payload.quantity == 3
    assert payload.source == "whatsapp_bulk_rfq"
    assert payload.is_bulk is True
    assert "Bulk RFQ items" in payload.notes


def test_format_ambiguous_match_message_offers_numbered_resolution_and_rfq_path():
    message = format_ambiguous_match_message(
        [
            {"name": "Hemodialysis Catheter"},
            {"name": "Foley Catheter"},
            {"name": "IV Cannula"},
            {"name": "Central Venous Catheter"},
        ]
    )

    assert "1. Hemodialysis Catheter" in message
    assert "Reply RFQ" in message
    assert "AGENT" in message
