import pytest
from fastapi import HTTPException

from app.core import auth


def test_require_api_key_accepts_x_api_key(monkeypatch):
    monkeypatch.setattr(auth, "API_KEY", "secret")

    auth.require_api_key(x_api_key="secret")


def test_require_api_key_accepts_bearer_token(monkeypatch):
    monkeypatch.setattr(auth, "API_KEY", "secret")

    auth.require_api_key(authorization="Bearer secret")


def test_require_api_key_rejects_missing_key(monkeypatch):
    monkeypatch.setattr(auth, "API_KEY", "secret")

    with pytest.raises(HTTPException) as exc:
        auth.require_api_key()

    assert exc.value.status_code == 401


def test_require_api_key_fails_closed_when_unconfigured(monkeypatch):
    monkeypatch.setattr(auth, "API_KEY", None)

    with pytest.raises(HTTPException) as exc:
        auth.require_api_key(x_api_key="secret")

    assert exc.value.status_code == 503
