from app.services.search import find_products


def test_generic_suture_search_diversifies_families_and_prefers_live_offer():
    products = [
        {
            "product_id": "pga-no-price",
            "name": "Absorbable Braided PGA Suture",
            "product_family_id": "SUTURE-PGA",
        },
        {
            "product_id": "pga-live",
            "name": "Absorbable Braided PGA Suture",
            "product_family_id": "SUTURE-PGA",
        },
        {
            "product_id": "pdo-live",
            "name": "Absorbable Monofilament PDO Suture",
            "product_family_id": "SUTURE-PDO",
        },
    ]
    aliases = [
        {"product_id": product["product_id"], "alias": "suture | sutures | surgical stitches"}
        for product in products
    ]
    inventory = [
        {"inventory_id": "i-pga-empty", "product_id": "pga-no-price", "brand": "Katsan"},
        {"inventory_id": "i-pga-live", "product_id": "pga-live", "brand": "JMS"},
        {"inventory_id": "i-pdo-live", "product_id": "pdo-live", "brand": "JMS"},
    ]
    data = {
        "products": products,
        "aliases": aliases,
        "inventory": inventory,
        "pricing": [
            {"pricing_id": "pr-pga", "inventory_id": "i-pga-live", "unit_price": 1000},
            {"pricing_id": "pr-pdo", "inventory_id": "i-pdo-live", "unit_price": 1200},
        ],
    }

    matches = find_products("sutures", products, aliases, limit=5, data=data)

    assert [match["product_id"] for match in matches] == ["pga-live", "pdo-live"]
    assert [match["search_display_name"] for match in matches] == ["PGA sutures", "PDO sutures"]


def test_search_matches_brand_and_pipe_separated_aliases():
    products = [{"product_id": "p1", "name": "Absorbable Suture"}]
    aliases = [{"product_id": "p1", "alias": "stitch | surgical thread"}]
    data = {
        "products": products,
        "aliases": aliases,
        "inventory": [{"inventory_id": "i1", "product_id": "p1", "brand": "Alcalactine"}],
        "pricing": [],
    }

    assert find_products("stitches", products, aliases, data=data)[0]["product_id"] == "p1"
    assert find_products("Alcalactine", products, aliases, data=data)[0]["product_id"] == "p1"


def test_generic_family_name_supports_catheters_and_prefers_a_live_variant():
    products = [
        {
            "product_id": "cvc-exact-no-price",
            "name": "Central venous catheter",
            "product_family_id": "FAM-CATH-CENTRAL-VENOUS",
            "product_family_name": "Central venous catheters",
        },
        {
            "product_id": "cvc-live",
            "name": "Central venous catheter kit, 7 Fr, triple lumen",
            "product_family_id": "FAM-CATH-CENTRAL-VENOUS",
            "product_family_name": "Central venous catheters",
        },
    ]
    data = {
        "products": products,
        "aliases": [],
        "inventory": [
            {"inventory_id": "i-cvc-empty", "product_id": "cvc-exact-no-price", "brand": "Generic"},
            {"inventory_id": "i-cvc-live", "product_id": "cvc-live", "brand": "JMS"},
        ],
        "pricing": [{"pricing_id": "pr-cvc", "inventory_id": "i-cvc-live", "unit_price": 25000}],
    }

    matches = find_products("central venous catheter", products, [], limit=5, data=data)

    assert [match["product_id"] for match in matches] == ["cvc-live"]
    assert matches[0]["search_display_name"] == "Central venous catheters"


def test_structured_variant_attributes_are_searchable():
    products = [
        {
            "product_id": "foley-16",
            "name": "Foley urinary catheter",
            "product_family_id": "FAM-CATH-URINARY-FOLEY",
            "product_family_name": "Foley urinary catheters",
        }
    ]
    data = {
        "products": products,
        "aliases": [],
        "inventory": [],
        "pricing": [],
        "product_attributes": [
            {
                "product_id": "foley-16",
                "attribute_code": "size",
                "value": "16",
                "unit": "CH",
            },
            {
                "product_id": "foley-16",
                "attribute_code": "lumens",
                "value": "2",
                "unit": None,
            },
        ],
    }

    matches = find_products("size 16 CH", products, [], data=data)

    assert [match["product_id"] for match in matches] == ["foley-16"]
