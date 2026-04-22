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

    assert categories == ["consumables", "devices"]


def test_get_products_returns_live_catalog_rows(monkeypatch):
    monkeypatch.setattr(catalog_access, "get_cached_data", _sample_catalog_data)

    products = catalog_access.get_products()

    assert len(products) == 3
    assert products[0]["product_id"] == "p1"


def test_get_products_by_category_filters_rows(monkeypatch):
    monkeypatch.setattr(catalog_access, "get_cached_data", _sample_catalog_data)

    products = catalog_access.get_products_by_category("consumables")

    assert [product["product_id"] for product in products] == ["p3", "p1"]


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
