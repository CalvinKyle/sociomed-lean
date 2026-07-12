import asyncio

from app.core.states import ConversationState
from app.data_access import catalog as catalog_access
from app.services import whatsapp_service


def _sample_data():
    return {
        "products": [
            {"product_id": "p1", "name": "Surgical Gloves", "category": "consumables"},
            {"product_id": "p2", "name": "Oxygen Mask", "category": "devices"},
        ],
        "aliases": [
            {"alias": "gloves", "product_id": "p1"},
            {"alias": "mask", "product_id": "p2"},
        ],
        "inventory": [
            {
                "inventory_id": "i1",
                "product_id": "p1",
                "vendor_id": "v1",
                "brand": "SafeTouch",
                "uom": "Box of 100",
                "stock_qty": 250,
                "lead_time_days": 2,
            }
        ],
        "pricing": [
            {"pricing_id": "pr1", "inventory_id": "i1", "min_qty": 10, "max_qty": 99, "unit_price": 1200},
            {"pricing_id": "pr2", "inventory_id": "i1", "min_qty": 100, "max_qty": None, "unit_price": 1100},
        ],
        "vendors": [
            {"vendor_id": "v1", "name": "MedSource", "phone": "+256700111111"},
        ],
        "inventory_by_product": {
            "p1": [
                {
                    "inventory_id": "i1",
                    "product_id": "p1",
                    "vendor_id": "v1",
                    "brand": "SafeTouch",
                    "uom": "Box of 100",
                    "stock_qty": 250,
                    "lead_time_days": 2,
                }
            ],
        },
        "vendors_by_id": {
            "v1": {"vendor_id": "v1", "name": "MedSource", "phone": "+256700111111"},
        },
        "pricing_by_inventory": {
            "i1": [
                {"pricing_id": "pr1", "inventory_id": "i1", "min_qty": 10, "max_qty": 99, "unit_price": 1200},
                {"pricing_id": "pr2", "inventory_id": "i1", "min_qty": 100, "max_qty": None, "unit_price": 1100},
            ],
        },
    }


def test_whatsapp_category_browse_flows_into_offer_selection(monkeypatch):
    session_store = {"256700111111": {"state": ConversationState.MENU.value}}
    sent_messages = []

    async def fake_send_whatsapp_message(_to, message):
        sent_messages.append(message)
        return True

    def fake_get_session(user):
        return session_store.get(user)

    def fake_save_session(user, data):
        session_store[user] = data

    monkeypatch.setattr(catalog_access, "get_cached_data", _sample_data)
    monkeypatch.setattr(whatsapp_service, "get_cached_data", _sample_data)
    monkeypatch.setattr(whatsapp_service, "send_whatsapp_message", fake_send_whatsapp_message)
    monkeypatch.setattr(whatsapp_service, "get_session", fake_get_session)
    monkeypatch.setattr(whatsapp_service, "save_session", fake_save_session)
    monkeypatch.setattr(whatsapp_service, "record_funnel_event", lambda *_args, **_kwargs: None)

    sender = "256700111111"

    asyncio.run(whatsapp_service.handle_incoming_message({"from": sender, "text": {"body": "6"}}))
    assert "Browse procurement categories" in sent_messages[-1]
    assert session_store[sender]["state"] == ConversationState.BROWSING_CATEGORIES.value

    asyncio.run(whatsapp_service.handle_incoming_message({"from": sender, "text": {"body": "1"}}))
    assert "Consumables products" in sent_messages[-1]
    assert session_store[sender]["state"] == ConversationState.CATEGORY_SELECTED.value

    asyncio.run(whatsapp_service.handle_incoming_message({"from": sender, "text": {"body": "1"}}))
    assert "Available Supplier Offers" in sent_messages[-1]
    assert session_store[sender]["state"] == ConversationState.VIEWING_RESULTS.value
    assert session_store[sender]["product"]["product_id"] == "p1"


def test_fuzzy_category_and_product_selection(monkeypatch):
    monkeypatch.setattr(
        whatsapp_service,
        "get_products_by_category",
        lambda _category: [
            {"product_id": "p1", "name": "Surgical Gloves"},
            {"product_id": "p2", "name": "Examination Table"},
        ],
    )

    assert whatsapp_service._resolve_category_selection(
        "consumibles", ["consumables", "equipment"]
    ) == "consumables"
    assert whatsapp_service._resolve_category_product_selection(
        "surgcal gloves", "consumables", []
    )["product_id"] == "p1"
    assert whatsapp_service._resolve_category_selection("mask", ["face masks", "oxygen masks"]) is None


def test_returning_sender_with_expired_session_gets_timeout_message(monkeypatch):
    sent_messages = []
    saved_sessions = {}

    async def fake_send(_to, message):
        sent_messages.append(message)
        return True

    monkeypatch.setattr(whatsapp_service, "get_session", lambda _user: None)
    monkeypatch.setattr(whatsapp_service, "has_seen_before", lambda _user: True)
    monkeypatch.setattr(whatsapp_service, "save_session", lambda user, data: saved_sessions.update({user: data}))
    monkeypatch.setattr(whatsapp_service, "send_whatsapp_message", fake_send)

    asyncio.run(
        whatsapp_service.handle_incoming_message(
            {"from": "256700111111", "text": {"body": "hello"}}
        )
    )

    assert "previous session timed out" in sent_messages[0]
    assert saved_sessions["256700111111"]["state"] == ConversationState.MENU.value


def test_cross_sell_click_records_funnel_event(monkeypatch):
    sender = "256700111111"
    events = []
    sent_messages = []
    sessions = {
        sender: {
            "state": ConversationState.VIEWING_RESULTS.value,
            "product": {"product_id": "p1", "name": "Surgical Gloves"},
            "related_products": [{"product_id": "p2", "product_name": "Oxygen Mask"}],
        }
    }
    data = _sample_data()
    data["products_by_id"] = {
        "p1": data["products"][0],
        "p2": data["products"][1],
    }

    async def fake_send(_to, message):
        sent_messages.append(message)
        return True

    monkeypatch.setattr(whatsapp_service, "get_session", lambda user: sessions.get(user))
    monkeypatch.setattr(whatsapp_service, "save_session", lambda user, value: sessions.update({user: value}))
    monkeypatch.setattr(whatsapp_service, "send_whatsapp_message", fake_send)
    monkeypatch.setattr(whatsapp_service, "get_cached_data", lambda: data)
    monkeypatch.setattr(whatsapp_service, "get_results", lambda *_args, **_kwargs: [{"brand": "AirFlow"}])
    monkeypatch.setattr(whatsapp_service, "format_results", lambda *_args, **_kwargs: ("offers", []))
    monkeypatch.setattr(whatsapp_service, "_append_related_products", lambda reply, *_args: (reply, []))
    monkeypatch.setattr(
        whatsapp_service,
        "record_funnel_event",
        lambda event_type, **kwargs: events.append((event_type, kwargs)),
    )

    asyncio.run(
        whatsapp_service.handle_incoming_message(
            {"from": sender, "text": {"body": "R1"}}
        )
    )

    assert events == [
        (
            "cross_sell_click",
            {
                "source": "whatsapp",
                "actor_id": sender,
                "data": {
                    "from_product_id": "p1",
                    "to_product_id": "p2",
                    "position": 1,
                },
            },
        )
    ]
