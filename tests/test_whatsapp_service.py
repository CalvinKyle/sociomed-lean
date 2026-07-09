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
