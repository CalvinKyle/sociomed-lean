import asyncio
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
from twilio.request_validator import RequestValidator

from app.api import routes
from app.core import utils
from app.services.twilio_adapter import extract_twilio_message


def _client():
    app = FastAPI()
    app.include_router(routes.router)
    return TestClient(app)


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


def test_twilio_webhook_enqueues_internal_message(monkeypatch):
    client = _client()
    queued = []

    monkeypatch.setattr(routes, "_verify_twilio_signature", lambda *_args: True)
    monkeypatch.setattr(routes, "claim_whatsapp_message", lambda _message_id: True)
    monkeypatch.setattr(routes.process_whatsapp_message, "delay", lambda message: queued.append(message))

    response = client.post(
        "/api/webhook/twilio",
        data={
            "MessageSid": "SM123",
            "From": "whatsapp:+256700111111",
            "Body": "hello",
            "NumMedia": "0",
        },
        headers={"X-Twilio-Signature": "test-signature"},
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/xml")
    assert queued == [
        {
            "id": "SM123",
            "from": "+256700111111",
            "type": "text",
            "text": {"body": "hello"},
        }
    ]


def test_twilio_webhook_rejects_invalid_signature(monkeypatch):
    client = _client()
    monkeypatch.setattr(routes, "_verify_twilio_signature", lambda *_args: False)

    response = client.post(
        "/api/webhook/twilio",
        data={"MessageSid": "SM123", "From": "whatsapp:+256700111111", "Body": "hello"},
        headers={"X-Twilio-Signature": "invalid"},
    )

    assert response.status_code == 403


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

    result = asyncio.run(utils.send_whatsapp_message_result("+256700111111", "Welcome to SocioMed"))

    assert result.success is True
    assert result.provider_message_id == "SMOUTBOUND"
    assert captured["credentials"] == ("AC123", "auth-token")
    assert captured["payload"] == {
        "body": "Welcome to SocioMed",
        "from_": "whatsapp:+14155238886",
        "to": "whatsapp:+256700111111",
        "status_callback": "https://sociomed-beta.onrender.com/api/webhook/twilio/status",
    }
