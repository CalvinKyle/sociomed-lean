from datetime import datetime, timedelta
from types import SimpleNamespace

from app.services import rfq_digest


class _VendorQuery:
    def __init__(self, vendors):
        self.vendors = vendors

    def filter(self, *_args):
        return self

    def all(self):
        return self.vendors


class _FakeDb:
    def __init__(self, vendors):
        self.vendors = vendors

    def query(self, _model):
        return _VendorQuery(self.vendors)

    def close(self):
        pass


def test_digest_includes_computable_commission_and_skips_missing_rate(monkeypatch):
    now = datetime(2026, 7, 12, 12, 0, 0)
    changed_at = now - timedelta(hours=1)
    rfqs = [
        SimpleNamespace(
            id=1,
            product_name="Surgical Gloves",
            quantity=10,
            organization="City Clinic",
            vendor_id="v1",
            order_value=1_000_000,
            currency="UGX",
            status="confirmed",
            created_at=now - timedelta(days=2),
            status_updated_at=changed_at,
        ),
        SimpleNamespace(
            id=2,
            product_name="IV Sets",
            quantity=20,
            organization="City Clinic",
            vendor_id="v2",
            order_value=500_000,
            currency="UGX",
            status="fulfilled",
            created_at=now - timedelta(days=2),
            status_updated_at=changed_at,
        ),
    ]
    vendors = [
        SimpleNamespace(vendor_id="v1", commission_rate=8.5),
        SimpleNamespace(vendor_id="v2", commission_rate=None),
    ]
    monkeypatch.setattr(rfq_digest, "SessionLocal", lambda: _FakeDb(vendors))
    monkeypatch.setattr(rfq_digest, "get_recent_rfqs", lambda _db, _cutoff: rfqs)

    digest = rfq_digest.build_daily_rfq_digest(now)

    assert "est. total: 85,000 UGX" in digest
    assert "#1 Surgical Gloves" in digest
    assert "#2 IV Sets — order" not in digest
