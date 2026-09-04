import asyncio

import pytest

from app.services import whatsapp_service


@pytest.mark.parametrize(
    ("message", "expected_label"),
    [
        ({"type": "image", "image": {"id": "media-id"}}, "photo"),
        ({"type": "audio", "audio": {"id": "media-id"}}, "voice note"),
        ({"type": "document", "document": {"id": "media-id"}}, "document"),
        ({"type": "location", "location": {"latitude": 0.31, "longitude": 32.58}}, "location"),
        ({"type": "interactive", "interactive": {"type": "button_reply"}}, "interactive message"),
    ],
)
def test_handle_incoming_message_replies_to_non_text_without_changing_session(
    monkeypatch,
    message,
    expected_label,
):
    replies = []
    saved_sessions = []
    audit_events = []

    async def fake_send_whatsapp_message(to, reply_text):
        replies.append((to, reply_text))
        return True

    monkeypatch.setattr(whatsapp_service, "send_whatsapp_message", fake_send_whatsapp_message)
    monkeypatch.setattr(whatsapp_service, "get_session", lambda sender: {"state": "DIRECT_RFQ"})
    monkeypatch.setattr(whatsapp_service, "save_session", lambda sender, data: saved_sessions.append((sender, data)))
    monkeypatch.setattr(
        whatsapp_service,
        "log_audit_event",
        lambda sender, event_type, data: audit_events.append((sender, event_type, data)),
    )

    message = {"from": "256700111111", **message}

    asyncio.run(whatsapp_service.handle_incoming_message(message))

    assert replies == [
        (
            "256700111111",
            f"I received your {expected_label}, but this procurement flow works best with typed text right now.\n\n"
            "Please type your reply as text so I can keep helping you. You can also send 0 to return to the main menu.",
        )
    ]
    assert saved_sessions == []
    assert audit_events == [
        (
            "256700111111",
            "unsupported_whatsapp_message",
            {"message_type": message["type"]},
        )
    ]


def test_handle_incoming_message_processes_text_payloads(monkeypatch):
    replies = []
    saved_sessions = []

    async def fake_send_whatsapp_message(to, reply_text):
        replies.append((to, reply_text))
        return True

    monkeypatch.setattr(whatsapp_service, "send_whatsapp_message", fake_send_whatsapp_message)
    monkeypatch.setattr(whatsapp_service, "get_session", lambda sender: {"state": "MENU"})
    monkeypatch.setattr(whatsapp_service, "save_session", lambda sender, data: saved_sessions.append((sender, data)))
    monkeypatch.setattr(whatsapp_service, "get_currency_for_phone", lambda sender: "UGX")
    monkeypatch.setattr(whatsapp_service, "get_cached_data", lambda: {"products": [], "aliases": []})
    monkeypatch.setattr(whatsapp_service, "get_categories", lambda: [])
    monkeypatch.setattr(whatsapp_service, "_load_buyer_profile", lambda _sender: None)

    asyncio.run(
        whatsapp_service.handle_incoming_message(
            {
                "from": "256700111111",
                "type": "text",
                "text": {"body": "hello"},
            }
        )
    )

    assert replies == [("256700111111", whatsapp_service._main_menu())]
    assert saved_sessions == [("256700111111", {"state": "MENU"})]


def test_first_message_product_with_quantity_bypasses_menu(monkeypatch):
    sender = "+256700111111"
    replies = []
    sessions = {}
    product = {"product_id": "p1", "name": "Surgical Gloves", "category": "consumables"}
    data = {
        "products": [product],
        "aliases": [{"alias": "gloves", "product_id": "p1"}],
        "inventory": [],
    }
    result = {
        "inventory_id": "i1",
        "product_id": "p1",
        "brand": "SafeTouch",
        "uom": "boxes",
        "stock_qty": 200,
        "lead_time_days": 3,
        "min_qty": 1,
        "default_price": 1200,
        "vendor_id": "v1",
        "vendor_name": "Private Supplier",
        "vendor_phone": "+256700000000",
        "pricing": [{"min_qty": 1, "max_qty": None, "unit_price": 1200}],
    }

    async def fake_send(_to, message):
        replies.append(message)
        return True

    monkeypatch.setattr(whatsapp_service, "get_session", lambda _sender: None)
    monkeypatch.setattr(whatsapp_service, "has_seen_before", lambda _sender: False)
    monkeypatch.setattr(whatsapp_service, "save_session", lambda user, value: sessions.update({user: value}))
    monkeypatch.setattr(whatsapp_service, "send_whatsapp_message", fake_send)
    monkeypatch.setattr(whatsapp_service, "get_currency_for_phone", lambda _sender: "UGX")
    monkeypatch.setattr(whatsapp_service, "get_cached_data", lambda: data)
    monkeypatch.setattr(whatsapp_service, "get_categories", lambda: ["consumables"])
    monkeypatch.setattr(whatsapp_service, "get_results", lambda *_args, **_kwargs: [result])
    monkeypatch.setattr(whatsapp_service, "get_related_catalog", lambda *_args, **_kwargs: [])

    asyncio.run(
        whatsapp_service.handle_incoming_message(
            {"from": sender, "type": "text", "text": {"body": "10 boxes of surgical gloves"}}
        )
    )

    assert "Requested quantity: 10 boxes" in replies[-1]
    assert "Available Options" in replies[-1]
    assert "Private Supplier" not in replies[-1]
    assert sessions[sender]["state"] == "VIEWING_RESULTS"


def test_first_message_medicine_request_is_rejected_safely(monkeypatch):
    replies = []
    sessions = {}

    async def fake_send(_to, message):
        replies.append(message)
        return True

    monkeypatch.setattr(whatsapp_service, "get_session", lambda _sender: None)
    monkeypatch.setattr(whatsapp_service, "save_session", lambda user, value: sessions.update({user: value}))
    monkeypatch.setattr(whatsapp_service, "send_whatsapp_message", fake_send)
    monkeypatch.setattr(whatsapp_service, "get_cached_data", lambda: {"products": [], "aliases": []})
    monkeypatch.setattr(whatsapp_service, "get_categories", lambda: [])

    asyncio.run(
        whatsapp_service.handle_incoming_message(
            {"from": "+256700111111", "type": "text", "text": {"body": "amoxicillin capsules"}}
        )
    )

    assert "not medicines" in replies[-1]
    assert sessions["+256700111111"]["state"] == "MENU"
