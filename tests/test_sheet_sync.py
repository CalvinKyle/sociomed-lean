import pytest

from app.core.sheet_sync import (
    prepare_sheet_data,
    split_multi_value_cell,
    summarize_vendor_phone_issues,
    validate_catalog_snapshot,
)


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
        "vendors": [{"VendorID": "v1", "Name": "MedSource", "Phone": "256700111111", "Email": "sales@medsource.com ", "Region": "Kampala"}],
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
        "pricing": [{"Pricing ID": "pr1", "Inventory ID": "i1", "Min Qty": "10", "Max Qty": "99", "Unit Price": "1200"}],
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

    try:
        prepare_sheet_data(raw_data)
    except ValueError as exc:
        assert "category" in str(exc)
    else:
        raise AssertionError("prepare_sheet_data should reject missing required columns")


def test_summarize_vendor_phone_issues_counts_missing_and_invalid_numbers():
    summary = summarize_vendor_phone_issues(
        [
            {"phone": "+256700111111"},
            {"phone": ""},
            {"phone": "0700111111"},
        ]
    )

    assert summary == {"valid": 1, "missing": 1, "invalid": 1}


def test_validate_catalog_snapshot_accepts_linked_positive_catalog():
    validate_catalog_snapshot(
        {
            "products": [{"product_id": "p1", "name": "Suture", "category": "Consumables"}],
            "vendors": [{"vendor_id": "v1", "name": "Supplier"}],
            "inventory": [{"inventory_id": "i1", "product_id": "p1", "vendor_id": "v1"}],
            "pricing": [{"pricing_id": "pr1", "inventory_id": "i1", "min_qty": 1, "unit_price": 100}],
            "aliases": [{"alias": "suture | sutures", "product_id": "p1"}],
        }
    )


def test_validate_catalog_snapshot_rejects_orphans_and_blank_pricing_values():
    with pytest.raises(ValueError) as exc_info:
        validate_catalog_snapshot(
            {
                "products": [{"product_id": "p1", "name": "Suture", "category": "Consumables"}],
                "vendors": [{"vendor_id": "v1", "name": "Supplier"}],
                "inventory": [{"inventory_id": "i1", "product_id": "missing", "vendor_id": "v1"}],
                "pricing": [{"pricing_id": "", "inventory_id": "orphan", "min_qty": 1, "unit_price": ""}],
                "aliases": [{"alias": "", "product_id": "p1"}],
            }
        )

    error = str(exc_info.value)
    assert "missing pricing_id, unit_price" in error
    assert "unknown product_id 'missing'" in error
    assert "unknown inventory_id 'orphan'" in error
