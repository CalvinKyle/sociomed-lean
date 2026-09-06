import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models.db import Base, CatalogChangeLog, Vendor
from sync_sheets_to_db import sync_catalog_snapshot
from tests.test_sheet_sync import _valid_snapshot


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()


def test_vendor_values_are_coerced_before_comparison(db):
    first = _valid_snapshot()
    sync_catalog_snapshot(db, first)

    second = _valid_snapshot()
    second["vendors"][0]["commission_rate"] = 8.5
    second["vendors"][0]["is_own_inventory"] = True
    run = sync_catalog_snapshot(db, second)

    vendor = db.get(Vendor, "v1")
    assert vendor.commission_rate == 8.5
    assert vendor.is_own_inventory is True
    assert run.summary["vendors"]["unchanged"] == 1
    assert (
        db.query(CatalogChangeLog)
        .filter(
            CatalogChangeLog.version_id == run.version_id,
            CatalogChangeLog.entity_type == "vendor",
        )
        .count()
        == 0
    )


def test_blank_optional_vendor_values_preserve_existing_database_values(db):
    sync_catalog_snapshot(db, _valid_snapshot())
    second = _valid_snapshot()
    second["vendors"][0]["commission_rate"] = ""
    second["vendors"][0]["is_own_inventory"] = ""

    run = sync_catalog_snapshot(db, second)

    vendor = db.get(Vendor, "v1")
    assert vendor.commission_rate == 8.5
    assert vendor.is_own_inventory is True
    assert run.summary["vendors"]["unchanged"] == 1
