from app.core import utils


class _FakeRedis:
    def __init__(self):
        self.store: dict[str, str] = {}

    def set(self, key, value, nx=False, ex=None):
        if nx and key in self.store:
            return None
        self.store[key] = value
        return True


def test_claim_whatsapp_message_allows_first_delivery(monkeypatch):
    monkeypatch.setattr(utils, "redis_client", _FakeRedis())

    assert utils.claim_whatsapp_message("wamid.1") is True


def test_claim_whatsapp_message_rejects_redelivery(monkeypatch):
    monkeypatch.setattr(utils, "redis_client", _FakeRedis())

    assert utils.claim_whatsapp_message("wamid.1") is True
    assert utils.claim_whatsapp_message("wamid.1") is False


def test_claim_whatsapp_message_treats_different_ids_independently(monkeypatch):
    monkeypatch.setattr(utils, "redis_client", _FakeRedis())

    assert utils.claim_whatsapp_message("wamid.1") is True
    assert utils.claim_whatsapp_message("wamid.2") is True


def test_claim_whatsapp_message_fails_open_without_id(monkeypatch):
    fake_redis = _FakeRedis()
    monkeypatch.setattr(utils, "redis_client", fake_redis)

    assert utils.claim_whatsapp_message(None) is True
    assert utils.claim_whatsapp_message("") is True
    assert fake_redis.store == {}
