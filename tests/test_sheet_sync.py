import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.sheet_sync import (
    prepare_sheet_data,
    split_multi_value_cell,
    summarize_vendor_phone_issues,
    validate_catalog_snapshot,
)
from app.models.db import (
    Alias,
    Base,
    CatalogChangeLog,
    Inventory,
    Pricing,
    Product,
    SyncVersion,
)
from sync_sheets_to_db import (
    get_catalog_change_history,
    list_sync_versions,
    sync_catalog_snapshot,
)


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()


def _valid_snapshot():
    return {
        "products": [
            {
                "product_id": "p1",
                "name": "Suture",
                "category": "Consumables",
                "clinical_speciality": "Surgery",
                "related_ids": "",
                "product_family_id": "SUTURE-PGA",
                "equipment_review_required": "FALSE",
            }
        ],
        "vendors": [
            {
                "vendor_id": "v1",
                "name": "Supplier",
                "phone": "+256700111111",
                "email": "sales@example.com",
                "region": "Kampala",
                "commission_rate": "8.5",
                "is_own_inventory": "TRUE",
            }
        ],
        "inventory": [
            {
                "inventory_id": "i1",
                "sku": "SUT-1",
                "product_id": "p1",
                "vendor_id": "v1",
                "brand": "SafeStitch",
                "uom": "BP12",
                "stock_qty": "5.0",
                "lead_time_days": "2",
            }
        ],
        "pricing": [
            {
                "pricing_id": "pr1",
                "inventory_id": "i1",
                "min_qty": "1.0",
                "max_qty": "10",
                "unit_price": "32,879",
                "price_valid_until": "2026-12-31",
            }
        ],
        "aliases": [{"alias": "suture | sutures", "product_id": "p1"}],
    }


def test_repeat_sync_is_unchanged_and_creates_no_second_change_entries(db):
    first = sync_catalog_snapshot(db, _valid_snapshot())
    second_snapshot = _valid_snapshot()
    second_snapshot["vendors"][0]["commission_rate"] = 8.5
    second_snapshot["vendors"][0]["is_own_inventory"] = True
    second_snapshot["inventory"][0]["stock_qty"] = 5
    second_snapshot["pricing"][0]["unit_price"] = 32879.0

    second = sync_catalog_snapshot(db, second_snapshot)

    assert first.summary["products"]["created"] == 1
    for tab_name in ("products", "vendors", "inventory", "pricing"):
        assert second.summary[tab_name] == {
            "unchanged": 1,
            "changed": 0,
            "created": 0,
            "skipped_invalid": 0,
        }
    assert second.summary["aliases"] == {
        "unchanged": 2,
        "changed": 0,
        "created": 0,
        "skipped_invalid": 0,
    }
    assert (
        db.query(CatalogChangeLog)
        .filter(CatalogChangeLog.version_id == second.version_id)
        .count()
        == 0
    )
    assert db.query(SyncVersion).count() == 2


def test_blank_stock_quantity_matches_persisted_zero_on_repeat_sync(db):
    snapshot = _valid_snapshot()
    snapshot["inventory"][0]["stock_qty"] = ""

    sync_catalog_snapshot(db, snapshot)
    second = sync_catalog_snapshot(db, snapshot)

    assert db.get(Inventory, "i1").stock_qty == 0
    assert second.summary["inventory"]["unchanged"] == 1
    assert second.summary["inventory"]["changed"] == 0


def test_dry_run_rolls_back_catalog_and_version_history(db):
    result = sync_catalog_snapshot(db, _valid_snapshot(), dry_run=True)

    assert result.version_id is None
    assert db.query(Product).count() == 0
    assert db.query(SyncVersion).count() == 0
    assert db.query(CatalogChangeLog).count() == 0


def test_mixed_valid_invalid_rows_sync_valid_and_log_dependency_skips(db):
    snapshot = _valid_snapshot()
    snapshot["products"].append(
        {"product_id": "p2", "name": "", "category": "Consumables"}
    )
    snapshot["inventory"].append(
        {
            "inventory_id": "i2",
            "product_id": "p2",
            "vendor_id": "v1",
            "brand": "Skipped",
            "uom": "unit",
        }
    )
    snapshot["pricing"].append(
        {
            "pricing_id": "pr2",
            "inventory_id": "i2",
            "min_qty": 1,
            "unit_price": 100,
        }
    )
    snapshot["aliases"].append({"alias": "bad product", "product_id": "p2"})

    run = sync_catalog_snapshot(db, snapshot)

    assert db.get(Product, "p1") is not None
    assert db.get(Product, "p2") is None
    assert db.get(Inventory, "i1") is not None
    assert db.get(Inventory, "i2") is None
    assert db.get(Pricing, "pr1") is not None
    assert db.get(Pricing, "pr2") is None
    assert db.query(Alias).filter(Alias.product_id == "p2").count() == 0

    skipped = (
        db.query(CatalogChangeLog)
        .filter(
            CatalogChangeLog.version_id == run.version_id,
            CatalogChangeLog.change_type == "skipped_invalid",
        )
        .all()
    )
    reasons = {entry.entity_id: entry.reason for entry in skipped}
    assert "missing name" in reasons["p2"]
    assert "product_id 'p2' did not pass validation" in reasons["i2"]
    assert "inventory_id 'i2' did not pass validation" in reasons["pr2"]
    assert "product_id 'p2' did not pass validation" in reasons["p2:bad product"]
    assert run.summary["products"]["skipped_invalid"] == 1
    assert run.summary["inventory"]["skipped_invalid"] == 1
    assert run.summary["pricing"]["skipped_invalid"] == 1
    assert run.summary["aliases"]["skipped_invalid"] == 1


def test_single_field_change_logs_only_changed_record_with_before_and_after(db):
    sync_catalog_snapshot(db, _valid_snapshot())
    changed = _valid_snapshot()
    changed["products"][0]["category"] = "Surgical consumables"

    run = sync_catalog_snapshot(db, changed)

    entries = (
        db.query(CatalogChangeLog)
        .filter(CatalogChangeLog.version_id == run.version_id)
        .all()
    )
    assert len(entries) == 1
    entry = entries[0]
    assert entry.entity_type == "product"
    assert entry.entity_id == "p1"
    assert entry.change_type == "updated"
    assert entry.before_state["category"] == "Consumables"
    assert entry.after_state["category"] == "Surgical consumables"
    assert run.summary["products"]["changed"] == 1
    assert run.summary["vendors"]["unchanged"] == 1

    versions = list_sync_versions(db)
    history = get_catalog_change_history(db, entity_id="p1")
    assert versions[0]["version_id"] == run.version_id
    assert versions[0]["summary"]["products"]["changed"] == 1
    assert [item["change_type"] for item in history] == ["updated", "created"]


def test_aliases_are_incrementally_added_removed_and_logged(db):
    sync_catalog_snapshot(db, _valid_snapshot())
    changed = _valid_snapshot()
    changed["aliases"] = [{"alias": "stitch", "product_id": "p1"}]

    run = sync_catalog_snapshot(db, changed)

    assert [row.alias for row in db.query(Alias).all()] == ["stitch"]
    alias_changes = (
        db.query(CatalogChangeLog)
        .filter(
            CatalogChangeLog.version_id == run.version_id,
            CatalogChangeLog.entity_type == "alias",
        )
        .all()
    )
    assert sorted(entry.change_type for entry in alias_changes) == [
        "created",
        "removed",
        "removed",
    ]
    assert run.summary["aliases"] == {
        "unchanged": 0,
        "changed": 2,
        "created": 1,
        "skipped_invalid": 0,
    }


def test_invalid_alias_row_does_not_delete_existing_aliases_for_that_product(db):
    sync_catalog_snapshot(db, _valid_snapshot())
    changed = _valid_snapshot()
    changed["aliases"] = [
        {"alias": "suture", "product_id": "p1"},
        {"alias": "", "product_id": "p1"},
    ]

    run = sync_catalog_snapshot(db, changed)

    assert sorted(row.alias for row in db.query(Alias).all()) == ["suture", "sutures"]
    assert run.summary["aliases"]["unchanged"] == 1
    assert run.summary["aliases"]["changed"] == 0
    assert run.summary["aliases"]["skipped_invalid"] == 1


def test_duplicate_primary_key_keeps_first_occurrence():
    snapshot = _valid_snapshot()
    snapshot["products"].append(
        {"product_id": "p1", "name": "Last write", "category": "Wrong"}
    )

    result = validate_catalog_snapshot(snapshot)

    assert result.data["products"] == [snapshot["products"][0]]
    duplicate = next(issue for issue in result.skipped if issue.tab_name == "products")
    assert duplicate.entity_id == "p1"
    assert "first seen on row 2" in duplicate.reason


def test_prepare_sheet_data_normalizes_headers_and_vendor_phone():
    raw_data = {
        "products": [
            {
                " Product ID ": " p1 ",
                "Name": " Surgical Gloves ",
                "Category": " consumables ",
                "Clinical Speciality": " dentistry, surgery ",
                "Related IDs": "p2; p3",
            }
        ],
        "vendors": [
            {
                "VendorID": "v1",
                "Name": "MedSource",
                "Phone": "256700111111",
                "Email": "sales@medsource.com ",
                "Region": "Kampala",
            }
        ],
        "inventory": [
            {
                "Inventory ID": "i1",
                "Product ID": "p1",
                "Vendor ID": "v1",
                "SKU": " SM-GLOVE-001 ",
                "Brand": "SafeTouch",
                "UOM": "Box of 100",
                "Stock Qty": "250",
                "Lead Time Days": "2",
            }
        ],
        "pricing": [
            {
                "Pricing ID": "pr1",
                "Inventory ID": "i1",
                "Min Qty": "10",
                "Max Qty": "99",
                "Unit Price": "1200",
            }
        ],
        "aliases": [{"Alias": "gloves", "Product ID": "p1"}],
    }

    prepared = prepare_sheet_data(raw_data)

    assert prepared["products"][0]["product_id"] == "p1"
    assert prepared["products"][0]["name"] == "Surgical Gloves"
    assert prepared["products"][0]["clinical_speciality"] == "dentistry | surgery"
    assert prepared["products"][0]["related_ids"] == "p2 | p3"
    assert prepared["vendors"][0]["phone"] == "+256700111111"
    assert prepared["inventory"][0]["sku"] == "SM-GLOVE-001"
    assert prepared["inventory"][0]["uom"] == "Box of 100"


def test_split_multi_value_cell_accepts_commas_semicolons_and_pipes():
    assert split_multi_value_cell("dentistry, surgery | emergency; ICU") == [
        "dentistry",
        "surgery",
        "emergency",
        "ICU",
    ]


def test_prepare_sheet_data_raises_for_missing_required_columns():
    raw_data = {
        "products": [{"product_id": "p1", "name": "Surgical Gloves"}],
        "vendors": [],
        "inventory": [],
        "pricing": [],
        "aliases": [],
    }

    with pytest.raises(ValueError, match="category"):
        prepare_sheet_data(raw_data)


def test_summarize_vendor_phone_issues_counts_missing_and_invalid_numbers():
    summary = summarize_vendor_phone_issues(
        [
            {"phone": "+256700111111"},
            {"phone": ""},
            {"phone": "0700111111"},
        ]
    )

    assert summary == {"valid": 1, "missing": 1, "invalid": 1}


def test_validate_catalog_snapshot_filters_orphans_and_bad_pricing():
    snapshot = _valid_snapshot()
    snapshot["inventory"].append(
        {"inventory_id": "orphan", "product_id": "missing", "vendor_id": "v1"}
    )
    snapshot["pricing"].append(
        {
            "pricing_id": "bad-price",
            "inventory_id": "orphan",
            "min_qty": 0,
            "max_qty": -1,
            "unit_price": 0,
        }
    )

    result = validate_catalog_snapshot(snapshot)

    assert [row["inventory_id"] for row in result.data["inventory"]] == ["i1"]
    assert [row["pricing_id"] for row in result.data["pricing"]] == ["pr1"]
    reasons = "\n".join(issue.reason for issue in result.skipped)
    assert "unknown product_id 'missing'" in reasons
    assert "min_qty must be at least 1" in reasons
    assert "unit_price must be greater than 0" in reasons
    assert "max_qty cannot be less than min_qty" in reasons


def _versioned_taxonomy_snapshot():
    snapshot = _valid_snapshot()
    snapshot.update(
        {
            "taxonomy_versions": [
                {
                    "version_id": "2026-09",
                    "name": "September taxonomy",
                    "status": "active",
                }
            ],
            "product_classes": [
                {
                    "class_id": "CLASS-SUTURE",
                    "name": "Sutures",
                    "approval_status": "approved",
                }
            ],
            "product_families": [
                {
                    "family_id": "SUTURE-PGA",
                    "name": "PGA sutures",
                    "class_id": "CLASS-SUTURE",
                    "approval_status": "approved",
                }
            ],
            "taxonomy_version_families": [
                {"version_id": "2026-09", "family_id": "SUTURE-PGA"}
            ],
            "product_taxonomy_assignments": [
                {
                    "version_id": "2026-09",
                    "product_id": "p1",
                    "family_id": "SUTURE-PGA",
                    "approval_status": "approved",
                }
            ],
            "clinical_specialties": [
                {"specialty_code": "SURGERY", "name": "Surgery"}
            ],
            "product_specialties": [
                {
                    "version_id": "2026-09",
                    "product_id": "p1",
                    "specialty_code": "SURGERY",
                    "is_primary": True,
                    "approval_status": "approved",
                }
            ],
            "product_attributes": [
                {
                    "version_id": "2026-09",
                    "product_id": "p1",
                    "attribute_code": "size",
                    "value": "0",
                    "unit": None,
                    "approval_status": "approved",
                }
            ],
        }
    )
    return snapshot


def test_active_taxonomy_with_pending_rows_is_filtered_not_raised():
    snapshot = _versioned_taxonomy_snapshot()
    snapshot["product_specialties"][0]["approval_status"] = "pending"

    result = validate_catalog_snapshot(snapshot)

    assert result.data["taxonomy_versions"] == []
    assert result.data["product_classes"] == []
    assert result.data["product_specialties"] == []
    assert any(
        "product_specialties are not approved" in issue.reason
        for issue in result.skipped
    )


def test_repeat_sync_leaves_versioned_taxonomy_rows_unchanged(db):
    snapshot = _versioned_taxonomy_snapshot()
    sync_catalog_snapshot(db, snapshot)

    second = sync_catalog_snapshot(db, snapshot)

    assert (
        db.query(CatalogChangeLog)
        .filter(CatalogChangeLog.version_id == second.version_id)
        .count()
        == 0
    )
    for tab_name in (
        "taxonomy_versions",
        "product_classes",
        "product_families",
        "taxonomy_version_families",
        "product_taxonomy_assignments",
        "clinical_specialties",
        "product_specialties",
        "product_attributes",
    ):
        assert second.summary[tab_name]["changed"] == 0
        assert second.summary[tab_name]["created"] == 0
        assert second.summary[tab_name]["unchanged"] == 1
