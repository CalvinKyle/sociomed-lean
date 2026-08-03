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

    asyncio.run(
        whatsapp_service.handle_incoming_message(
            {
                "from": "256700111111",
                "type": "text",
                "text": {"body": "5"},
            }
        )
    )

    assert replies == [("256700111111", whatsapp_service._help_message())]
    assert saved_sessions == [("256700111111", {"state": "MENU"})]


def test_operator_message_is_intercepted_before_conversation_state_routing(monkeypatch):
    calls = []

    class FakeDb:
        def close(self):
            calls.append("db_closed")

    async def fake_handle(_db, sender, text):
        calls.append((sender, text))
        return False

    monkeypatch.setattr(whatsapp_service, "SALES_AGENT_PHONE", "+256700999999")
    monkeypatch.setattr(whatsapp_service, "SessionLocal", FakeDb)
    monkeypatch.setattr(whatsapp_service, "handle_operator_pfi_command", fake_handle)
    monkeypatch.setattr(
        whatsapp_service,
        "get_session",
        lambda _sender: (_ for _ in ()).throw(AssertionError("operator reached buyer routing")),
    )

    asyncio.run(
        whatsapp_service.handle_incoming_message(
            {"from": "256700999999", "type": "text", "text": {"body": "unrelated"}}
        )
    )

    assert calls == [("256700999999", "unrelated"), "db_closed"]


def test_yes_shaped_message_from_non_operator_uses_normal_buyer_routing(monkeypatch):
    replies = []
    operator_calls = []

    async def fake_send(_to, message):
        replies.append(message)
        return True

    async def fake_operator(*args):
        operator_calls.append(args)
        return True

    monkeypatch.setattr(whatsapp_service, "SALES_AGENT_PHONE", "+256700999999")
    monkeypatch.setattr(whatsapp_service, "handle_operator_pfi_command", fake_operator)
    monkeypatch.setattr(whatsapp_service, "get_session", lambda _sender: {"state": "MENU"})
    monkeypatch.setattr(whatsapp_service, "send_whatsapp_message", fake_send)

    asyncio.run(
        whatsapp_service.handle_incoming_message(
            {"from": "256700111111", "type": "text", "text": {"body": "YES 42"}}
        )
    )

    assert operator_calls == []
    assert replies == ["Please reply with a number from 1 to 6."]


def test_more_routes_to_sales_with_a_buyer_message(monkeypatch):
    replies = []
    saved_sessions = []

    async def fake_send(_to, message):
        replies.append(message)
        return True

    monkeypatch.setattr(whatsapp_service, "get_session", lambda _sender: {"state": "VIEWING_RESULTS"})
    monkeypatch.setattr(whatsapp_service, "send_whatsapp_message", fake_send)
    monkeypatch.setattr(
        whatsapp_service,
        "save_session",
        lambda sender, data: saved_sessions.append((sender, data)),
    )

    asyncio.run(
        whatsapp_service.handle_incoming_message(
            {"from": "256700111111", "type": "text", "text": {"body": "MORE"}}
        )
    )

    assert replies == ["Reply with: name | organization | what you need.\nWe will connect you with sales."]
    assert saved_sessions[0][1]["state"] == "TALK_TO_AGENT"
