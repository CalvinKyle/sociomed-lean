from app.services.rfq_triage import (
    format_ambiguous_match_message,
    is_bulk_request,
    is_complex_bulk_request,
    parse_direct_rfq_message,
    resolve_bulk_line_items,
    split_requested_items,
)


def test_split_requested_items_detects_procurement_lists():
    items = split_requested_items("gloves x10, catheters x5 and IV sets x20")

    assert items == ["gloves x10", "catheters x5", "IV sets x20"]
    assert is_bulk_request("gloves x10, catheters x5")
    assert is_complex_bulk_request("a, b, c, d")


def test_parse_direct_rfq_message_keeps_single_item_rfq_specific():
    payload = parse_direct_rfq_message("Dr. Ali | surgical gloves | 10 | Mulago Hospital | Kampala")

    assert payload is not None
    assert payload.buyer_name == "Dr. Ali"
    assert payload.product_name == "surgical gloves"
    assert payload.quantity == 10
    assert payload.source == "whatsapp_direct_rfq"
    assert payload.is_bulk is False


def test_parse_direct_rfq_message_routes_bulk_lists_to_manual_triage():
    payload = parse_direct_rfq_message(
        "Dr. Ali | gloves x10, catheters x5, IV sets x20 | Mulago Hospital | Kampala"
    )

    assert payload is not None
    assert payload.buyer_name == "Dr. Ali"
    assert payload.product_name == "Bulk RFQ: gloves x10, catheters x5, IV sets x20"
    assert payload.quantity == 3
    assert payload.source == "whatsapp_bulk_rfq"
    assert payload.is_bulk is True
    assert "Bulk RFQ items" in payload.notes


def test_parse_direct_rfq_message_rejects_legacy_format_without_contact_name():
    assert parse_direct_rfq_message("surgical gloves | 10 | Mulago Hospital | Kampala") is None
    assert parse_direct_rfq_message(
        "gloves x10, catheters x5 | Mulago Hospital | Kampala"
    ) is None


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


def test_resolve_bulk_line_items_keeps_matched_and_unmatched_items(monkeypatch):
    from app.services import rfq_triage

    def fake_find_products(query, *_args, **_kwargs):
        if query == "gloves":
            return [{"product_id": "P-1", "name": "Surgical Gloves"}]
        return []

    monkeypatch.setattr(rfq_triage, "find_products", fake_find_products)
    monkeypatch.setattr(
        rfq_triage,
        "get_results",
        lambda *_args, **_kwargs: [
            {
                "vendor_id": "V-1",
                "vendor_name": "MedSource",
                "uom": "box",
                "default_price": 120_000,
            }
        ],
    )

    resolved = resolve_bulk_line_items(["gloves x10", "special tubing x3"], {})

    assert resolved[0] == {
        "product_id": "P-1",
        "product_name": "Surgical Gloves",
        "vendor_id": "V-1",
        "vendor_name": "MedSource",
        "quantity": 10,
        "uom": "box",
        "unit_price": 120_000,
    }
    assert resolved[1]["product_id"] is None
    assert resolved[1]["product_name"] == "special tubing"
    assert resolved[1]["quantity"] == 3
