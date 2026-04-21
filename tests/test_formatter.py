from app.models.formatter import format_results


def test_format_results_returns_selectable_offer_options():
    results = [
        {
            "inventory_id": "i1",
            "product_id": "p1",
            "brand": "SafeTouch",
            "stock_qty": 200,
            "lead_time_days": 3,
            "min_qty": 10,
            "default_price": 1200,
            "vendor_id": "v1",
            "vendor_phone": "256700111111",
            "vendor_name": "MedSource",
            "pricing": [
                {"min_qty": 10, "max_qty": 99, "unit_price": 1200},
                {"min_qty": 100, "max_qty": None, "unit_price": 1100},
            ],
        }
    ]

    message, option_map = format_results("Surgical Gloves", results, currency="UGX")

    assert "Available Supplier Offers" in message
    assert "SafeTouch" in message
    assert option_map[0]["vendor_name"] == "MedSource"
    assert option_map[0]["min_qty"] == 10
