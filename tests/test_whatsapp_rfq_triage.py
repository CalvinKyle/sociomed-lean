import asyncio

from app.core.states import ConversationState
from app.services import whatsapp_service


def test_ambiguous_search_match_can_be_resolved_by_number(monkeypatch):
    sender = "256700111111"
    session_store = {sender: {"state": ConversationState.SEARCHING.value}}
    sent_messages = []
    products = [
        {"product_id": "p1", "name": "Hemodialysis Catheter"},
        {"product_id": "p2", "name": "Foley Catheter"},
    ]

    async def fake_send_whatsapp_message(_to, message):
        sent_messages.append(message)
        return True

    def fake_get_session(user):
        return session_store.get(user)

    def fake_save_session(user, data):
        session_store[user] = data

    monkeypatch.setattr(whatsapp_service, "send_whatsapp_message", fake_send_whatsapp_message)
    monkeypatch.setattr(whatsapp_service, "get_session", fake_get_session)
    monkeypatch.setattr(whatsapp_service, "save_session", fake_save_session)
    monkeypatch.setattr(whatsapp_service, "get_cached_data", lambda: {"products": products, "aliases": []})
    monkeypatch.setattr(whatsapp_service, "find_products", lambda *_args, **_kwargs: products)
    monkeypatch.setattr(whatsapp_service, "get_results", lambda *_args, **_kwargs: [{"brand": "SafeLine"}])
    monkeypatch.setattr(
        whatsapp_service,
        "format_results",
        lambda product_name, _results, currency: (f"Available Supplier Offers for {product_name}", [{"brand": "SafeLine"}]),
    )

    asyncio.run(whatsapp_service.handle_incoming_message({"from": sender, "text": {"body": "catheter"}}))

    assert "I found multiple possible matches" in sent_messages[-1]
    assert session_store[sender]["state"] == ConversationState.SEARCH_DISAMBIGUATION.value

    asyncio.run(whatsapp_service.handle_incoming_message({"from": sender, "text": {"body": "2"}}))

    assert "Available Supplier Offers for Foley Catheter" in sent_messages[-1]
    assert session_store[sender]["state"] == ConversationState.VIEWING_RESULTS.value
    assert session_store[sender]["product"]["product_id"] == "p2"


def test_bulk_direct_rfq_is_logged_for_manual_triage(monkeypatch):
    sender = "256700111111"
    session_store = {sender: {"state": ConversationState.DIRECT_RFQ.value}}
    sent_messages = []
    created_payload = {}
    audit_events = []

    async def fake_send_whatsapp_message(_to, message):
        sent_messages.append(message)
        return True

    async def fake_create_whatsapp_rfq(**kwargs):
        created_payload.update(kwargs)
        return 77, False

    def fake_get_session(user):
        return session_store.get(user)

    def fake_save_session(user, data):
        session_store[user] = data

    monkeypatch.setattr(whatsapp_service, "send_whatsapp_message", fake_send_whatsapp_message)
    monkeypatch.setattr(whatsapp_service, "_create_whatsapp_rfq", fake_create_whatsapp_rfq)
    monkeypatch.setattr(whatsapp_service, "get_session", fake_get_session)
    monkeypatch.setattr(whatsapp_service, "save_session", fake_save_session)
    monkeypatch.setattr(whatsapp_service, "log_audit_event", lambda phone, event, data: audit_events.append((phone, event, data)))

    asyncio.run(
        whatsapp_service.handle_incoming_message(
            {"from": sender, "text": {"body": "gloves x10, catheters x5 | Mulago Hospital | Kampala"}}
        )
    )

    assert created_payload["source"] == "whatsapp_bulk_rfq"
    assert created_payload["product_name"] == "Bulk RFQ: gloves x10, catheters x5"
    assert "Bulk RFQ items" in created_payload["notes"]
    assert "bulk quotation request has been logged" in sent_messages[-1]
    assert any(event == "bulk_rfq_triaged" for _, event, _ in audit_events)
