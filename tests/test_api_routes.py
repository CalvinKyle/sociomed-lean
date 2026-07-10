from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import routes
from app.core import auth
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

    def fake_mark_rfq_status(_db, rfq_id, status):
        return SimpleNamespace(id=rfq_id, status=status.strip().lower())

    monkeypatch.setattr(routes, "mark_rfq_status", fake_mark_rfq_status)

    response = client.patch(
        "/api/rfqs/5/status",
        json={"status": "Quoted"},
        headers={"X-API-Key": "secret"},
    )

    assert response.status_code == 200
    assert response.json() == {"rfq_id": 5, "status": "quoted"}


def test_update_rfq_status_returns_404_for_missing_rfq(monkeypatch):
    client = _client(monkeypatch)
    monkeypatch.setattr(routes, "mark_rfq_status", lambda _db, _rfq_id, _status: None)

    response = client.patch(
        "/api/rfqs/999/status",
        json={"status": "quoted"},
        headers={"Authorization": "Bearer secret"},
    )

    assert response.status_code == 404
