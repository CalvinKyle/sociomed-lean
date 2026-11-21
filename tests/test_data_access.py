from app.data_access import catalog as catalog_access
from app.core.states import ConversationState
from app.core.validators import (
    validate_delivery_location,
    validate_facility_name,
    validate_product_exists,
    validate_quantity,
    validate_state,
)


def _sample_catalog_data():
    return {
        "products": [
            {"product_id": "p1", "name": "Surgical Gloves", "category": "consumables"},
            {"product_id": "p2", "name": "Oxygen Mask", "category": "devices"},
            {"product_id": "p3", "name": "Nitrile Gloves", "category": "consumables"},
        ],
        "aliases": [{"alias": "gloves", "product_id": "p1"}],
    }


def test_get_categories_returns_sorted_unique_values(monkeypatch):
    monkeypatch.setattr(catalog_access, "get_cached_data", _sample_catalog_data)

    categories = catalog_access.get_categories()

    assert categories == ["Consumables", "Devices"]


def test_get_products_returns_live_catalog_rows(monkeypatch):
    monkeypatch.setattr(catalog_access, "get_cached_data", _sample_catalog_data)

    products = catalog_access.get_products()

    assert len(products) == 3
    assert products[0]["product_id"] == "p1"


def test_get_products_by_category_filters_rows(monkeypatch):
    monkeypatch.setattr(catalog_access, "get_cached_data", _sample_catalog_data)

    products = catalog_access.get_products_by_category("consumables")

    assert [product["product_id"] for product in products] == ["p3", "p1"]


def test_buyer_categories_merge_devices_and_use_family_classification(monkeypatch):
    data = {
        "products": [
            {"product_id": "p1", "name": "Transducer Protector", "category": "Device"},
            {"product_id": "p2", "name": "BP Monitor", "category": "Devices"},
            {
                "product_id": "p3",
                "name": "Chemistry Detergent",
                "category": "Equipment",
                "product_family_id": "FAM-SUB-LABORATORY-REAGENTS-9C37E9",
            },
            {
                "product_id": "p4",
                "name": "Barraquer Forceps",
                "category": "Devices",
                "product_family_id": "FAM-INSTR-FORCEPS",
            },
            {
                "product_id": "p5",
                "name": "Face Shield",
                "category": "Imaging",
                "product_family_id": "FAM-SUB-RADIOLOGY-CONSUMABLES-7D0602",
            },
        ]
    }
    monkeypatch.setattr(catalog_access, "get_cached_data", lambda: data)

    assert catalog_access.get_categories() == [
        "Consumables",
        "Devices",
        "Instruments",
        "Reagents",
    ]
    assert {p["product_id"] for p in catalog_access.get_products_by_category("Devices")} == {"p1", "p2"}


def test_category_subcategories_normalize_specialty_synonyms(monkeypatch):
    data = {
        "products": [
            {
                "product_id": "p1",
                "name": "Analyzer",
                "category": "Equipment",
                "clinical_speciality": "LABORATORY_MEDICINE | Laboratory diagnostics",
            },
            {
                "product_id": "p2",
                "name": "X-ray machine",
                "category": "Equipment",
                "clinical_speciality": "RADIOLOGY_IMAGING | RADIOLOGY",
            },
        ]
    }
    monkeypatch.setattr(catalog_access, "get_cached_data", lambda: data)

    assert catalog_access.get_subcategories_by_category("Equipment") == [
        "Laboratory",
        "Radiology & Imaging",
    ]


def test_equipment_subcategories_prioritize_clinical_navigation(monkeypatch):
    specialties = [
        "General Medical",
        "Respiratory Care",
        "RADIOLOGY",
        "CARDIOLOGY",
        "NEPHROLOGY",
        "LABORATORY_MEDICINE",
    ]
    monkeypatch.setattr(
        catalog_access,
        "get_cached_data",
        lambda: {
            "products": [
                {
                    "product_id": f"p{index}",
                    "name": f"Equipment {index}",
                    "category": "Equipment",
                    "clinical_speciality": specialty,
                }
                for index, specialty in enumerate(specialties)
            ]
        },
    )

    assert catalog_access.get_subcategories_by_category("Equipment")[:4] == [
        "Laboratory",
        "Nephrology",
        "Cardiology",
        "Radiology & Imaging",
    ]


def test_validation_helpers_cover_current_procurement_flow():
    products = _sample_catalog_data()["products"]

    assert validate_quantity(5)
    assert not validate_quantity(0)
    assert validate_product_exists("p1", products)
    assert not validate_product_exists("missing", products)
    assert validate_facility_name("Mulago Hospital")
    assert validate_delivery_location("Kampala")
    assert validate_state(ConversationState.SEARCHING.value)
    assert not validate_state("CHECKOUT")


def test_get_config_exposes_rfq_first_operating_model():
    config = catalog_access.get_config()

    assert config["operating_model"] == "rfq_first"
