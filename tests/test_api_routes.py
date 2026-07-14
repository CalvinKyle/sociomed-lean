from datetime import date
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import routes
from app.core import auth
from app.core.rfq_status import InvalidRFQStatus
from app.models.db import get_db


def _client(monkeypatch):
    app = FastAPI()
    app.include_router(routes.router)
    app.dependency_overrides[get_db] = lambda: object()
    monkeypatch.setattr(auth, "API_KEY", "secret")
    return TestClient(app)


def test_catalog_browse_is_public(monkeypatch):
    client = _client(monkeypatch)
    monkeypatch.setattr(routes, "get_categories", lambda: ["consumables"])

    response = client.get("/api/catalog/categories")

    assert response.status_code == 200
    assert response.json() == {"total_categories": 1, "categories": ["consumables"]}


def test_liveness_is_public_and_returns_process_status(monkeypatch):
    client = _client(monkeypatch)

    response = client.get("/api/health/liveness")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_meta_webhook_verification_is_public(monkeypatch):
    client = _client(monkeypatch)
    monkeypatch.setattr(routes, "VERIFY_TOKEN", "verify-me")

    response = client.get(
        "/api/webhook",
        params={
            "hub.mode": "subscribe",
            "hub.verify_token": "verify-me",
            "hub.challenge": "challenge-token",
        },
    )

    assert response.status_code == 200
    assert response.text == "challenge-token"


def test_protected_endpoint_requires_api_key(monkeypatch):
    client = _client(monkeypatch)

    response = client.get("/api/health")

    assert response.status_code == 401


def test_update_rfq_status_requires_api_key(monkeypatch):
    client = _client(monkeypatch)

    response = client.patch("/api/rfqs/5/status", json={"status": "quoted"})

    assert response.status_code == 401


def test_update_rfq_status_returns_updated_status(monkeypatch):
    client = _client(monkeypatch)

    def fake_mark_rfq_status(_db, rfq_id, status, order_value=None):
        return SimpleNamespace(id=rfq_id, status=status.strip().lower())

    async def fake_notify(_rfq):
        return False

    monkeypatch.setattr(routes, "mark_rfq_status", fake_mark_rfq_status)
    monkeypatch.setattr(routes, "notify_buyer_of_status_change", fake_notify)

    response = client.patch(
        "/api/rfqs/5/status",
        json={"status": "Quoted"},
        headers={"X-API-Key": "secret"},
    )

    assert response.status_code == 200
    assert response.json() == {"rfq_id": 5, "status": "quoted"}


def test_update_rfq_status_returns_404_for_missing_rfq(monkeypatch):
    client = _client(monkeypatch)
    monkeypatch.setattr(routes, "mark_rfq_status", lambda _db, _rfq_id, _status, order_value=None: None)

    response = client.patch(
        "/api/rfqs/999/status",
        json={"status": "quoted"},
        headers={"Authorization": "Bearer secret"},
    )

    assert response.status_code == 404


def test_update_rfq_status_returns_400_for_unknown_status(monkeypatch):
    client = _client(monkeypatch)

    def reject_status(*_args, **_kwargs):
        raise InvalidRFQStatus("Use one of: new, quoted, confirmed, fulfilled, cancelled, lost.")

    monkeypatch.setattr(routes, "mark_rfq_status", reject_status)

    response = client.patch(
        "/api/rfqs/5/status",
        json={"status": "in_review"},
        headers={"X-API-Key": "secret"},
    )

    assert response.status_code == 400
    assert "confirmed" in response.json()["detail"]


def test_update_rfq_status_notifies_buyer_and_passes_order_value(monkeypatch):
    client = _client(monkeypatch)
    calls = []

    def fake_mark(_db, rfq_id, status, order_value=None):
        calls.append((rfq_id, status, order_value))
        return SimpleNamespace(id=rfq_id, status="confirmed")

    async def fake_notify(rfq):
        calls.append(("notify", rfq.id))
        return True

    monkeypatch.setattr(routes, "mark_rfq_status", fake_mark)
    monkeypatch.setattr(routes, "notify_buyer_of_status_change", fake_notify)

    response = client.patch(
        "/api/rfqs/5/status",
        json={"status": "confirmed", "order_value": 250000},
        headers={"X-API-Key": "secret"},
    )

    assert response.status_code == 200
    assert calls == [(5, "confirmed", 250000), ("notify", 5)]


def test_download_pfi_returns_pdf_and_persists_reference(monkeypatch):
    rfq = SimpleNamespace(
        id=5,
        buyer_name="Dr. Ali",
        organization="Key Care Mobile Medical Services",
        currency="UGX",
        pfi_reference=None,
        created_at=date(2025, 2, 17),
    )

    class FakeQuery:
        def filter(self, *_args):
            return self

        def first(self):
            return rfq

    class FakeDb:
        committed = False

        def query(self, _model):
            return FakeQuery()

        def commit(self):
            self.committed = True

    db = FakeDb()
    app = FastAPI()
    app.include_router(routes.router)
    app.dependency_overrides[get_db] = lambda: db
    monkeypatch.setattr(auth, "API_KEY", "secret")
    monkeypatch.setattr(routes, "get_rfq_line_items", lambda *_args: [object()])
    monkeypatch.setattr(routes, "generate_pfi_pdf", lambda *_args: b"%PDF-test")

    response = TestClient(app).get(
        "/api/rfqs/5/pfi.pdf",
        headers={"X-API-Key": "secret"},
    )

    assert response.status_code == 200
    assert response.content == b"%PDF-test"
    assert response.headers["content-type"] == "application/pdf"
    assert 'filename="PFI_KCMS_170225_05.pdf"' in response.headers["content-disposition"]
    assert db.committed is True
