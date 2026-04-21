import importlib

import pytest

from app.core import config as config_module


def _reload_config(monkeypatch, **env):
    managed_keys = {
        "APP_ENV",
        "VERIFY_TOKEN",
        "WHATSAPP_TOKEN",
        "PHONE_NUMBER_ID",
        "WHATSAPP_APP_SECRET",
        "GOOGLE_CREDS_FILE",
        "GOOGLE_CREDS_JSON",
        "SHEET_NAME",
        "DATABASE_URL",
        "REDIS_URL",
        "REDIS_HOST",
        "REDIS_PORT",
        "REDIS_DB",
        "CACHE_TTL_SECONDS",
        "SESSION_TTL",
        "DEFAULT_CURRENCY",
        "PUBLIC_BASE_URL",
        "SUPPORT_EMAIL",
        "SALES_AGENT_PHONE",
        "ENABLE_OPEN_DOCS",
    }

    for key in managed_keys:
        monkeypatch.delenv(key, raising=False)

    for key, value in env.items():
        if value is None:
            monkeypatch.delenv(key, raising=False)
        else:
            monkeypatch.setenv(key, str(value))

    return importlib.reload(config_module)


def test_build_redis_url_preserves_credentials_and_switches_databases(monkeypatch):
    config = _reload_config(
        monkeypatch,
        APP_ENV="development",
        DATABASE_URL="sqlite:///./test.db",
        REDIS_URL="redis://default:s3cr3t@redis.example.com:6379/0",
    )

    assert config.build_redis_url() == "redis://default:s3cr3t@redis.example.com:6379/0"
    assert config.build_redis_url(db=1) == "redis://default:s3cr3t@redis.example.com:6379/1"


def test_validate_config_allows_local_start_without_whatsapp_credentials(monkeypatch):
    config = _reload_config(
        monkeypatch,
        APP_ENV="development",
        DATABASE_URL="sqlite:///./test.db",
        REDIS_HOST="localhost",
    )

    config.validate_config()


def test_validate_config_requires_whatsapp_and_public_routing_in_production(monkeypatch):
    config = _reload_config(
        monkeypatch,
        APP_ENV="production",
        DATABASE_URL="sqlite:///./test.db",
        REDIS_HOST="localhost",
        VERIFY_TOKEN="",
        WHATSAPP_TOKEN="",
        PHONE_NUMBER_ID="",
        WHATSAPP_APP_SECRET="",
        SALES_AGENT_PHONE="",
        PUBLIC_BASE_URL="",
    )

    with pytest.raises(Exception) as exc:
        config.validate_config()

    message = str(exc.value)
    assert "VERIFY_TOKEN" in message
    assert "WHATSAPP_TOKEN" in message
    assert "PHONE_NUMBER_ID" in message
    assert "PUBLIC_BASE_URL" in message
