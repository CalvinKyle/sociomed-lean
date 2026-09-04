import importlib

import pytest

from app.core import config as config_module


def _reload_config(monkeypatch, **env):
    managed_keys = {
        "APP_ENV",
        "WHATSAPP_PROVIDER",
        "ASYNC_WHATSAPP_PROCESSING",
        "VERIFY_TOKEN",
        "WHATSAPP_TOKEN",
        "PHONE_NUMBER_ID",
        "WHATSAPP_APP_SECRET",
        "TWILIO_ACCOUNT_SID",
        "TWILIO_AUTH_TOKEN",
        "TWILIO_WHATSAPP_FROM",
        "TWILIO_WEBHOOK_URL",
        "TWILIO_STATUS_CALLBACK_URL",
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
        "SESSION_VERSION",
        "DEFAULT_CURRENCY",
        "DB_POOL_SIZE",
        "DB_MAX_OVERFLOW",
        "DB_POOL_RECYCLE_SECONDS",
        "EXCHANGE_RATES_JSON",
        "EXCHANGE_RATES_LAST_UPDATED",
        "MAX_EXCHANGE_RATE_AGE_DAYS",
        "PUBLIC_BASE_URL",
        "SUPPORT_EMAIL",
        "SALES_AGENT_PHONE",
        "ENABLE_OPEN_DOCS",
        "API_KEY",
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


def test_async_whatsapp_processing_defaults_to_enabled(monkeypatch):
    config = _reload_config(monkeypatch)

    assert config.ASYNC_WHATSAPP_PROCESSING is True


def test_async_whatsapp_processing_can_be_disabled_for_sandbox(monkeypatch):
    config = _reload_config(monkeypatch, ASYNC_WHATSAPP_PROCESSING="false")

    assert config.ASYNC_WHATSAPP_PROCESSING is False


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
        API_KEY="",
    )

    with pytest.raises(Exception) as exc:
        config.validate_config()

    message = str(exc.value)
    assert "VERIFY_TOKEN" in message
    assert "WHATSAPP_TOKEN" in message
    assert "PHONE_NUMBER_ID" in message
    assert "GOOGLE_CREDS_JSON_OR_EXISTING_GOOGLE_CREDS_FILE" in message
    assert "PUBLIC_BASE_URL" in message
    assert "API_KEY" in message


def test_validate_config_requires_twilio_credentials_when_twilio_is_selected(monkeypatch):
    config = _reload_config(
        monkeypatch,
        APP_ENV="production",
        WHATSAPP_PROVIDER="twilio",
        DATABASE_URL="sqlite:///./test.db",
        REDIS_HOST="localhost",
        GOOGLE_CREDS_JSON="{}",
        SALES_AGENT_PHONE="+256700222222",
        PUBLIC_BASE_URL="https://sociomed-beta.onrender.com",
        API_KEY="secret",
        TWILIO_ACCOUNT_SID="",
        TWILIO_AUTH_TOKEN="",
        TWILIO_WHATSAPP_FROM="",
        TWILIO_WEBHOOK_URL="",
    )

    with pytest.raises(Exception) as exc:
        config.validate_config()

    message = str(exc.value)
    assert "TWILIO_ACCOUNT_SID" in message
    assert "TWILIO_AUTH_TOKEN" in message
    assert "TWILIO_WHATSAPP_FROM" in message
    assert "TWILIO_WEBHOOK_URL" in message
    assert "VERIFY_TOKEN" not in message


def test_validate_config_accepts_complete_twilio_production_settings(monkeypatch):
    config = _reload_config(
        monkeypatch,
        APP_ENV="production",
        WHATSAPP_PROVIDER="twilio",
        ASYNC_WHATSAPP_PROCESSING="false",
        DATABASE_URL="sqlite:///./test.db",
        REDIS_HOST="localhost",
        GOOGLE_CREDS_JSON="{}",
        SALES_AGENT_PHONE="+256700222222",
        PUBLIC_BASE_URL="https://sociomed-beta.onrender.com",
        API_KEY="secret",
        TWILIO_ACCOUNT_SID="AC123",
        TWILIO_AUTH_TOKEN="auth-token",
        TWILIO_WHATSAPP_FROM="whatsapp:+14155238886",
        TWILIO_WEBHOOK_URL="https://sociomed-beta.onrender.com/api/webhook/twilio",
    )

    config.validate_config()
    assert config.ASYNC_WHATSAPP_PROCESSING is False
