from app.models.db import Vendor
from sync_sheets_to_db import _upsert_vendors


class _FakeDb:
    def __init__(self):
        self.objects = {}

    def get(self, _model, key):
        return self.objects.get(key)

    def add(self, obj):
        self.objects[obj.vendor_id] = obj


def test_vendor_upsert_coerces_rate_and_blank_does_not_clear_it():
    db = _FakeDb()

    assert _upsert_vendors(
        db,
        [{"vendor_id": "v1", "name": "MedSource", "commission_rate": "8.5"}],
    ) == (1, 0)
    assert db.objects["v1"].commission_rate == 8.5

    assert _upsert_vendors(
        db,
        [{"vendor_id": "v1", "name": "MedSource Updated", "commission_rate": ""}],
    ) == (0, 1)
    assert db.objects["v1"].commission_rate == 8.5
    assert db.objects["v1"].name == "MedSource Updated"


def test_vendor_upsert_coerces_owned_inventory_flag():
    db = _FakeDb()

    _upsert_vendors(
        db,
        [{"vendor_id": "zelus", "name": "Zelus Life", "is_own_inventory": "TRUE"}],
    )

    assert db.objects["zelus"].is_own_inventory is True
