import asyncio
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from twilio.request_validator import RequestValidator

from app.api import routes
from app.core import utils
from app.services.twilio_adapter import extract_twilio_message


@pytest.fixture(autouse=True)
def configure_twilio_provider(monkeypatch):
    monkeypatch.setattr(routes, "WHATSAPP_PROVIDER", "twilio")


def _client():
    app = FastAPI()
    app.include_router(routes.router)
    return TestClient(app)


def _twilio_payload(message_id: str = "SM123") -> dict[str, str]:
    return {
        "MessageSid": message_id,
        "From": "whatsapp:+256700111111",
        "Body": "hello",
        "NumMedia": "0",
    }


def test_extract_twilio_text_message_normalizes_whatsapp_sender():
    message = extract_twilio_message(
        {
            "MessageSid": "SM123",
            "From": "whatsapp:+256700111111",
            "Body": "5",
            "NumMedia": "0",
        }
    )

    assert message == {
        "id": "SM123",
        "from": "+256700111111",
        "type": "text",
        "text": {"body": "5"},
    }


def test_extract_twilio_media_message_uses_existing_unsupported_media_flow():
    message = extract_twilio_message(
        {
            "MessageSid": "MM123",
            "From": "whatsapp:+256700111111",
            "Body": "",
            "NumMedia": "1",
            "MediaContentType0": "image/jpeg",
            "MediaUrl0": "https://api.twilio.com/media/123",
        }
    )

    assert message["type"] == "image"
    assert message["image"]["content_type"] == "image/jpeg"


def test_twilio_signature_validation_uses_configured_public_url(monkeypatch):
    auth_token = "twilio-test-auth-token"
    public_url = "https://sociomed-beta.onrender.com/api/webhook/twilio"
    form_data = {
        "MessageSid": "SM123",
        "From": "whatsapp:+256700111111",
        "Body": "hello",
    }
    signature = RequestValidator(auth_token).compute_signature(public_url, form_data)

    monkeypatch.setattr(routes, "TWILIO_AUTH_TOKEN", auth_token)

    request = SimpleNamespace(url="http://internal-render-host/api/webhook/twilio")
    assert routes._verify_twilio_signature(request, form_data, signature, public_url) is True


def test_twilio_webhook_processes_message_synchronously(monkeypatch):
    client = _client()
    processed = []
    queued = []

    async def fake_process_now(message):
        processed.append(message)

    monkeypatch.setattr(routes, "ASYNC_WHATSAPP_PROCESSING", False)
    monkeypatch.setattr(routes, "_verify_twilio_signature", lambda *_args: True)
    monkeypatch.setattr(routes, "claim_whatsapp_message", lambda _message_id: True)
    monkeypatch.setattr(routes, "process_whatsapp_message_now", fake_process_now)
    monkeypatch.setattr(routes.process_whatsapp_message, "delay", lambda message: queued.append(message))

    response = client.post(
        "/api/webhook/twilio",
        data=_twilio_payload(),
        headers={"X-Twilio-Signature": "test-signature"},
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/xml")
    assert len(processed) == 1
    assert processed[0]["id"] == "SM123"
    assert queued == []


def test_twilio_webhook_enqueues_message_when_async_processing_is_enabled(monkeypatch):
    client = _client()
    processed = []
    queued = []

    async def fake_process_now(message):
        processed.append(message)

    monkeypatch.setattr(routes, "ASYNC_WHATSAPP_PROCESSING", True)
    monkeypatch.setattr(routes, "_verify_twilio_signature", lambda *_args: True)
    monkeypatch.setattr(routes, "claim_whatsapp_message", lambda _message_id: True)
    monkeypatch.setattr(routes, "process_whatsapp_message_now", fake_process_now)
    monkeypatch.setattr(routes.process_whatsapp_message, "delay", lambda message: queued.append(message))

    response = client.post(
        "/api/webhook/twilio",
        data=_twilio_payload(),
        headers={"X-Twilio-Signature": "test-signature"},
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/xml")
    assert len(queued) == 1
    assert queued[0]["id"] == "SM123"
    assert processed == []


@pytest.mark.parametrize("async_enabled", [False, True])
def test_twilio_webhook_skips_duplicate_in_both_processing_modes(monkeypatch, async_enabled):
    client = _client()
    processed = []
    queued = []

    async def fake_process_now(message):
        processed.append(message)

    monkeypatch.setattr(routes, "ASYNC_WHATSAPP_PROCESSING", async_enabled)
    monkeypatch.setattr(routes, "_verify_twilio_signature", lambda *_args: True)
    monkeypatch.setattr(routes, "claim_whatsapp_message", lambda _message_id: False)
    monkeypatch.setattr(routes, "process_whatsapp_message_now", fake_process_now)
    monkeypatch.setattr(routes.process_whatsapp_message, "delay", lambda message: queued.append(message))

    response = client.post(
        "/api/webhook/twilio",
        data=_twilio_payload("SM-DUPLICATE"),
        headers={"X-Twilio-Signature": "test-signature"},
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/xml")
    assert processed == []
    assert queued == []


@pytest.mark.parametrize("async_enabled", [False, True])
def test_twilio_webhook_releases_claim_when_processing_start_fails(monkeypatch, async_enabled):
    client = _client()
    released_claims = []

    async def fail_inline(_message):
        raise RuntimeError("inline processing failed")

    def fail_enqueue(_message):
        raise RuntimeError("Celery enqueue failed")

    monkeypatch.setattr(routes, "ASYNC_WHATSAPP_PROCESSING", async_enabled)
    monkeypatch.setattr(routes, "_verify_twilio_signature", lambda *_args: True)
    monkeypatch.setattr(routes, "claim_whatsapp_message", lambda _message_id: True)
    monkeypatch.setattr(routes, "release_whatsapp_message_claim", released_claims.append)
    monkeypatch.setattr(routes, "process_whatsapp_message_now", fail_inline)
    monkeypatch.setattr(routes.process_whatsapp_message, "delay", fail_enqueue)

    response = client.post(
        "/api/webhook/twilio",
        data=_twilio_payload("SM-RETRY"),
        headers={"X-Twilio-Signature": "test-signature"},
    )

    assert response.status_code == 500
    assert response.json() == {"status": "error"}
    assert released_claims == ["SM-RETRY"]


def test_twilio_webhook_rejects_invalid_signature(monkeypatch):
    client = _client()
    monkeypatch.setattr(routes, "_verify_twilio_signature", lambda *_args: False)

    response = client.post(
        "/api/webhook/twilio",
        data=_twilio_payload(),
        headers={"X-Twilio-Signature": "invalid"},
    )

    assert response.status_code == 403


def test_twilio_webhook_rejects_conversations_payload_instead_of_silently_ignoring(monkeypatch):
    client = _client()
    monkeypatch.setattr(routes, "_verify_twilio_signature", lambda *_args: True)

    response = client.post(
        "/api/webhook/twilio",
        data={
            "EventType": "onMessageAdded",
            "ConversationSid": "CH123",
            "MessageSid": "IM123",
            "Author": "whatsapp:+256700111111",
            "Body": "hello",
        },
        headers={"X-Twilio-Signature": "test-signature"},
    )

    assert response.status_code == 400
    assert "Programmable Messaging" in response.json()["detail"]


def test_twilio_readiness_reports_worker_free_sandbox_dependencies(monkeypatch):
    class FakeSession:
        def execute(self, _statement):
            return None

        def close(self):
            return None

    client = _client()
    monkeypatch.setattr(routes, "ASYNC_WHATSAPP_PROCESSING", False)
    monkeypatch.setattr(routes, "TWILIO_ACCOUNT_SID", "AC123")
    monkeypatch.setattr(routes, "TWILIO_AUTH_TOKEN", "auth-token")
    monkeypatch.setattr(routes, "TWILIO_WHATSAPP_FROM", "whatsapp:+14155238886")
    monkeypatch.setattr(
        routes,
        "TWILIO_WEBHOOK_URL",
        "https://sociomed-beta.onrender.com/api/webhook/twilio",
    )
    monkeypatch.setattr(routes, "SessionLocal", FakeSession)
    monkeypatch.setattr(routes, "redis_client", SimpleNamespace(ping=lambda: True))

    response = client.get("/api/health/twilio")

    assert response.status_code == 200
    assert response.json()["status"] == "ready"
    assert all(response.json()["checks"].values())


def test_twilio_outbound_message_uses_configured_credentials(monkeypatch):
    captured = {}

    class FakeMessages:
        def create(self, **payload):
            captured["payload"] = payload
            return SimpleNamespace(sid="SMOUTBOUND", status="queued", error_code=None)

    class FakeClient:
        def __init__(self, account_sid, auth_token):
            captured["credentials"] = (account_sid, auth_token)
            self.messages = FakeMessages()

    monkeypatch.setattr(utils, "Client", FakeClient)
    monkeypatch.setattr(utils, "WHATSAPP_PROVIDER", "twilio")
    monkeypatch.setattr(utils, "TWILIO_ACCOUNT_SID", "AC123")
    monkeypatch.setattr(utils, "TWILIO_AUTH_TOKEN", "auth-token")
    monkeypatch.setattr(utils, "TWILIO_WHATSAPP_FROM", "whatsapp:+14155238886")
    monkeypatch.setattr(
        utils,
        "TWILIO_STATUS_CALLBACK_URL",
        "https://sociomed-beta.onrender.com/api/webhook/twilio/status",
    )

    result = asyncio.run(utils.send_whatsapp_message_result("+256700111111", "Welcome"))

    assert result.success is True
    assert result.provider_message_id == "SMOUTBOUND"
    assert captured["credentials"] == ("AC123", "auth-token")
    assert captured["payload"] == {
        "body": "Welcome\n\nSocioMED",
        "from_": "whatsapp:+14155238886",
        "to": "whatsapp:+256700111111",
        "status_callback": "https://sociomed-beta.onrender.com/api/webhook/twilio/status",
    }


def test_brand_wordmark_is_appended_once_to_every_outbound_message():
    assert utils.brand_whatsapp_message("Please reply with a quantity.") == (
        "Please reply with a quantity.\n\nSocioMED"
    )
    assert utils.brand_whatsapp_message("Welcome to SocioMED.") == "Welcome to SocioMED."
