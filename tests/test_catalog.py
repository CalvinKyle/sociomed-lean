from app.services import catalog


def _sample_data():
    return {
        "products": [
            {"product_id": "p1", "name": "Surgical Gloves", "category": "consumables"},
            {"product_id": "p2", "name": "Oxygen Mask", "category": "devices"},
        ],
        "aliases": [
            {"alias": "gloves", "product_id": "p1"},
            {"alias": "mask", "product_id": "p2"},
            {"alias": "zelus", "product_id": "p1"},
            {"alias": "zelus", "product_id": "p2"},
        ],
        "inventory": [
            {
                "inventory_id": "i1",
                "product_id": "p1",
                "vendor_id": "v1",
                "brand": "SafeTouch",
                "uom": "Box of 100",
                "stock_qty": 250,
                "lead_time_days": 2,
            },
            {
                "inventory_id": "i2",
                "product_id": "p2",
                "vendor_id": "v2",
                "brand": "AirFlow",
                "uom": "Each",
                "stock_qty": 80,
                "lead_time_days": 4,
            },
        ],
        "pricing": [
            {"pricing_id": "pr1", "inventory_id": "i1", "min_qty": 10, "max_qty": 99, "unit_price": 1200},
            {"pricing_id": "pr2", "inventory_id": "i1", "min_qty": 100, "max_qty": None, "unit_price": 1100},
            {"pricing_id": "pr3", "inventory_id": "i2", "min_qty": 5, "max_qty": None, "unit_price": 4500},
        ],
        "vendors": [
            {"vendor_id": "v1", "name": "MedSource", "phone": "256700111111"},
            {"vendor_id": "v2", "name": "OxyPlus", "phone": "256700222222"},
        ],
        "inventory_by_product": {
            "p1": [
                {
                    "inventory_id": "i1",
                    "product_id": "p1",
                    "vendor_id": "v1",
                    "brand": "SafeTouch",
                    "uom": "Box of 100",
                    "stock_qty": 250,
                    "lead_time_days": 2,
                }
            ],
            "p2": [
                {
                    "inventory_id": "i2",
                    "product_id": "p2",
                    "vendor_id": "v2",
                    "brand": "AirFlow",
                    "uom": "Each",
                    "stock_qty": 80,
                    "lead_time_days": 4,
                }
            ],
        },
        "vendors_by_id": {
            "v1": {"vendor_id": "v1", "name": "MedSource", "phone": "256700111111"},
            "v2": {"vendor_id": "v2", "name": "OxyPlus", "phone": "256700222222"},
        },
        "pricing_by_inventory": {
            "i1": [
                {"pricing_id": "pr1", "inventory_id": "i1", "min_qty": 10, "max_qty": 99, "unit_price": 1200},
                {"pricing_id": "pr2", "inventory_id": "i1", "min_qty": 100, "max_qty": None, "unit_price": 1100},
            ],
            "i2": [
                {"pricing_id": "pr3", "inventory_id": "i2", "min_qty": 5, "max_qty": None, "unit_price": 4500},
            ],
        },
    }


def test_search_catalog_returns_live_offers(monkeypatch):
    monkeypatch.setattr(catalog, "get_cached_data", _sample_data)

    matches = catalog.search_catalog("gloves", limit=3)

    assert len(matches) == 1
    assert matches[0]["product_name"] == "Surgical Gloves"
    assert matches[0]["vendor_name"] == "MedSource"
    assert matches[0]["starting_price"] == 1100
    assert matches[0]["uom"] == "Box of 100"


def test_get_featured_catalog_returns_unique_products(monkeypatch):
    monkeypatch.setattr(catalog, "get_cached_data", _sample_data)

    featured = catalog.get_featured_catalog(limit=5)

    assert len(featured) == 2
    assert featured[0]["product_name"] == "Surgical Gloves"
    assert featured[1]["product_name"] == "Oxygen Mask"
    assert featured[0]["uom"] == "Box of 100"


def test_search_catalog_returns_multiple_products_for_shared_brand_alias(monkeypatch):
    monkeypatch.setattr(catalog, "get_cached_data", _sample_data)

    matches = catalog.search_catalog("Zelus", limit=5)

    product_names = {match["product_name"] for match in matches}
    assert "Surgical Gloves" in product_names
    assert "Oxygen Mask" in product_names
