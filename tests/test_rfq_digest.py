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
        SimpleNamespace(
            id=3,
            product_name="Patient Monitor",
            quantity=1,
            organization="Key Care",
            vendor_id="zelus",
            order_value=2_500_000,
            currency="UGX",
            status="fulfilled",
            created_at=now - timedelta(days=2),
            status_updated_at=changed_at,
        ),
    ]
    vendors = [
        SimpleNamespace(vendor_id="v1", name="MedSource", commission_rate=8.5, is_own_inventory=False),
        SimpleNamespace(vendor_id="v2", name="Other", commission_rate=None, is_own_inventory=False),
        SimpleNamespace(vendor_id="zelus", name="Zelus Life", commission_rate=None, is_own_inventory=True),
    ]
    monkeypatch.setattr(rfq_digest, "SessionLocal", lambda: _FakeDb(vendors))
    monkeypatch.setattr(rfq_digest, "get_recent_rfqs", lambda _db, _cutoff: rfqs)

    digest = rfq_digest.build_daily_rfq_digest(now)

    assert "Zelus commission revenue" in digest
    assert "est. total: 85,000 UGX" in digest
    assert "#1 Surgical Gloves" in digest
    assert "#2 IV Sets — order" not in digest
    assert "Zelus direct revenue (owned inventory, total: 2,500,000 UGX)" in digest
    assert "#3 Patient Monitor" in digest
