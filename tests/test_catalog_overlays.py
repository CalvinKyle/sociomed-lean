from app.services import whatsapp_service as service


def test_family_and_variant_ranges_keep_uoms_separate(monkeypatch):
    products = [{"product_id": "p1", "name": "Suture", "product_family_id": "f1"}]
    offers = [
        {"uom": "box of 10", "pricing": [{"unit_price": 100}, {"unit_price": 200}]},
        {"uom": "unit", "pricing": [{"unit_price": 10}, {"unit_price": 20}]},
    ]
    monkeypatch.setattr(service, "get_results", lambda *args, **kwargs: offers)
    family = service._build_product_groups(products, {}, "UGX")[0]
    variant = service._build_variant_options(products, {}, "UGX")[0]
    assert family["price_text"] == variant["price_text"]
    lines = family["price_text"].splitlines()
    assert len(lines) == 2
    assert "100" in lines[0] and "200" in lines[0] and "/ box of 10" in lines[0]
    assert "10" in lines[1] and "20" in lines[1] and "/ unit" in lines[1]


def test_ranges_keep_currencies_separate():
    text = service._offer_price_ranges([
        {"uom": "unit", "pricing": [{"currency": "KES", "unit_price": 100}]},
        {"uom": "unit", "pricing": [{"currency": "UGX", "unit_price": 5000}]},
    ], "UGX")
    assert len(text.splitlines()) == 2
    assert "KES" in text and "UGX" in text


def test_curated_family_order_precedes_fallback(monkeypatch):
    monkeypatch.setattr(service, "get_results", lambda *args, **kwargs: [])
    products = [{"product_id": name, "name": name, "product_family_id": name} for name in ("a", "b", "c", "d")]
    assert [g["family_key"] for g in service._build_product_groups(products, {}, "UGX")] == ["a", "b", "c", "d"]
    data = {"parent_products": [{"family_id": "d", "page": 1, "position": 2}, {"family_id": "c", "page": 1, "position": 1}, {"family_id": "b", "page": 2, "position": 1}]}
    assert [g["family_key"] for g in service._build_product_groups(products, data, "UGX")] == ["c", "d", "b", "a"]
