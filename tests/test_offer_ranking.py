from app.models.formatter import MAX_VISIBLE_OFFERS, format_results
from app.services.search import get_results, rank_offers


def _offer(
    name: str,
    price: int,
    *,
    owned: bool = False,
    stock: int = 10,
) -> dict:
    return {
        "inventory_id": name.lower(),
        "brand": name,
        "default_price": price,
        "pricing": [{"min_qty": 1, "max_qty": None, "unit_price": price}],
        "stock_qty": stock,
        "lead_time_days": 2,
        "is_own_inventory": owned,
    }


def test_owned_in_stock_and_within_threshold_ranks_first():
    ranked = rank_offers(
        [
            _offer("Partner", 90_000),
            _offer("Owned", 100_000, owned=True),
        ]
    )

    assert ranked[0]["brand"] == "Owned"


def test_partner_more_than_threshold_cheaper_ranks_first():
    ranked = rank_offers(
        [
            _offer("Owned", 100_000, owned=True),
            _offer("Partner", 89_999),
        ]
    )

    assert ranked[0]["brand"] == "Partner"
    assert {offer["brand"] for offer in ranked} == {"Owned", "Partner"}


def test_partner_ranks_first_when_owned_inventory_is_out_of_stock():
    ranked = rank_offers(
        [
            _offer("Owned", 80_000, owned=True, stock=0),
            _offer("Partner", 100_000),
        ]
    )

    assert ranked[0]["brand"] == "Partner"


def test_buyer_message_caps_offers_and_hides_supplier_identity_and_stock_quantity():
    offers = []
    for index in range(4):
        offer = _offer(f"Brand {index}", 100_000 + index)
        offer.update(
            {
                "vendor_id": f"secret-vendor-{index}",
                "vendor_name": f"Secret Supplier {index}",
                "vendor_phone": f"+25670000000{index}",
                "uom": "box",
            }
        )
        offers.append(offer)

    message, option_map = format_results("Surgical Gloves", offers)

    assert len(option_map) == MAX_VISIBLE_OFFERS == 3
    assert "Brand 3" not in message
    assert "Secret Supplier" not in message
    assert "secret-vendor" not in message
    assert "+256" not in message
    assert "Stock: 10" not in message
    assert "Stock: In Stock" in message
    assert "Reply MORE to talk to our sales team about other options" in message


def test_phone_currency_conversion_is_preserved_for_ranked_results():
    data = {
        "inventory_by_product": {
            "P-1": [
                {
                    "inventory_id": "I-1",
                    "product_id": "P-1",
                    "vendor_id": "V-1",
                    "brand": "SafeTouch",
                    "stock_qty": 10,
                    "lead_time_days": 2,
                }
            ]
        },
        "vendors_by_id": {
            "V-1": {
                "vendor_id": "V-1",
                "name": "Hidden Supplier",
                "is_own_inventory": False,
            }
        },
        "pricing_by_inventory": {
            "I-1": [
                {
                    "pricing_id": "PR-1",
                    "inventory_id": "I-1",
                    "min_qty": 1,
                    "max_qty": None,
                    "unit_price": 1_000,
                }
            ]
        },
    }

    uganda_offer = get_results("P-1", data, currency="UGX")[0]
    kenya_offer = get_results("P-1", data, currency="KES")[0]

    assert uganda_offer["default_price"] == 1_000
    assert kenya_offer["default_price"] == 29

