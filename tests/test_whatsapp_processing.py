import asyncio

import pytest

from app.services import tasks, whatsapp_processing


def test_process_whatsapp_message_now_reuses_handler_and_releases_lock(monkeypatch):
    calls = []
    message = {"id": "SM123", "from": "+256700111111"}

    async def fake_handle(payload):
        calls.append(("handle", payload))

    monkeypatch.setattr(whatsapp_processing, "acquire_session_lock", lambda sender: calls.append(("acquire", sender)) or True)
    monkeypatch.setattr(whatsapp_processing, "handle_incoming_message", fake_handle)
    monkeypatch.setattr(whatsapp_processing, "release_session_lock", lambda sender: calls.append(("release", sender)))

    asyncio.run(whatsapp_processing.process_whatsapp_message_now(message))

    assert calls == [
        ("acquire", "+256700111111"),
        ("handle", message),
        ("release", "+256700111111"),
    ]


def test_process_whatsapp_message_now_releases_lock_after_handler_error(monkeypatch):
    released = []
    message = {"id": "SM123", "from": "+256700111111"}

    async def fail_handle(_payload):
        raise RuntimeError("processing failed")

    monkeypatch.setattr(whatsapp_processing, "acquire_session_lock", lambda _sender: True)
    monkeypatch.setattr(whatsapp_processing, "handle_incoming_message", fail_handle)
    monkeypatch.setattr(whatsapp_processing, "release_session_lock", released.append)

    with pytest.raises(RuntimeError, match="processing failed"):
        asyncio.run(whatsapp_processing.process_whatsapp_message_now(message))

    assert released == ["+256700111111"]


def test_process_whatsapp_message_now_rejects_concurrent_sender(monkeypatch):
    message = {"id": "SM123", "from": "+256700111111"}
    monkeypatch.setattr(whatsapp_processing, "acquire_session_lock", lambda _sender: False)

    with pytest.raises(whatsapp_processing.WhatsAppMessageProcessingBusy):
        asyncio.run(whatsapp_processing.process_whatsapp_message_now(message))


def test_celery_task_reuses_shared_processor(monkeypatch):
    processed = []
    message = {"id": "SM123", "from": "+256700111111"}

    async def fake_process_now(payload):
        processed.append(payload)

    monkeypatch.setattr(tasks, "process_whatsapp_message_now", fake_process_now)

    tasks.process_whatsapp_message.run(message)

    assert processed == [message]
