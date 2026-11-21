"""Buyers must only ever see team-verified, unexpired prices."""

import asyncio
import json
from datetime import date, datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.catalogue_lint import lint_catalogue
from app.core.pricing import (
    PRICE_ON_QUOTATION,
    displayable_tiers,
    is_price_displayable,
    normalize_price_status,
)
from app.models import db as models
from app.models.formatter import format_results
from app.services import whatsapp_service
from app.services.search import get_results

TODAY = date(2026, 11, 21)


def _tier(**overrides):
    tier = {"min_qty": 1, "max_qty": None, "unit_price": 1000, "currency": "UGX", "price_status": "verified"}
    tier.update(overrides)
    return tier


@pytest.mark.parametrize(
    ("value", "expected"),
    [("verified", "verified"), (" Verified ", "verified"), ("VERIFIED", "verified"),
     ("unverified", "unverified"), ("indicative", "unverified"), ("yes", "unverified"),
     ("true", "unverified"), ("", "unverified"), (None, "unverified")],
)
def test_only_the_exact_word_verified_counts(value, expected):
    assert normalize_price_status(value) == expected


@pytest.mark.parametrize(
    ("tier", "expected"),
    [
        (_tier(), True),
        (_tier(price_status=None), False),
        (_tier(price_status="unverified"), False),
        ({"min_qty": 1, "unit_price": 1000}, False),  # column missing entirely
        (_tier(unit_price=0), False),
        (_tier(unit_price=None), False),
        (_tier(price_valid_until=None), True),
        (_tier(price_valid_until=TODAY), True),  # valid through the stated day
        (_tier(price_valid_until=TODAY - timedelta(days=1)), False),
        (_tier(price_valid_until="2026-11-20"), False),  # ISO string after the Redis round trip
        (_tier(price_valid_until="2026-12-31"), True),
        (_tier(price_valid_until="2026-12-31T00:00:00"), True),
        (_tier(price_valid_until="not a date"), False),  # unreadable date fails closed
        (_tier(price_valid_until=datetime(2026, 11, 20, 12, 0)), False),
    ],
)
def test_is_price_displayable_fails_closed(tier, expected):
    assert is_price_displayable(tier, TODAY) is expected


def test_verification_is_all_or_nothing_per_offer():
    ladder = [_tier(min_qty=1), _tier(min_qty=10, unit_price=900)]
    assert displayable_tiers(ladder, TODAY) == ladder
    ladder[1]["price_status"] = "unverified"
    assert displayable_tiers(ladder, TODAY) == []
    assert displayable_tiers([], TODAY) == []


def _data(tiers):
    return {
        "products_by_id": {"p": {"product_id": "p", "name": "Exam gloves", "active": True}},
        "inventory_by_product": {
            "p": [{"inventory_id": "i", "vendor_id": "v", "uom": "box", "brand": "Acme", "stock_qty": 7}]
        },
        "vendors_by_id": {"v": {"vendor_id": "v", "name": "Supplier"}},
        "pricing_by_inventory": {"i": tiers},
    }


def test_unverified_offer_is_visible_but_has_no_price():
    [offer] = get_results("p", _data([_tier(price_status="unverified")]))

    assert offer["pricing"] == []
    assert offer["default_price"] is None
    assert offer["price_verified"] is False
    assert offer["min_qty"] == 1  # ordering terms are not price


def test_verified_offer_keeps_prices_and_converts_currency():
    [offer] = get_results("p", _data([_tier(), _tier(min_qty=10, unit_price=900)]))

    assert offer["price_verified"] is True
    assert offer["default_price"] == 1000
    assert [tier["unit_price"] for tier in offer["pricing"]] == [1000, 900]


def test_partially_verified_or_expired_offer_shows_no_price():
    partial = [_tier(), _tier(min_qty=10, unit_price=900, price_status="unverified")]
    assert get_results("p", _data(partial))[0]["pricing"] == []
    expired = [_tier(price_valid_until="2000-01-01")]
    assert get_results("p", _data(expired))[0]["pricing"] == []


def test_unpriced_offers_sort_after_priced_ones():
    data = _data([_tier(price_status="unverified")])
    data["inventory_by_product"]["p"].append(
        {"inventory_id": "j", "vendor_id": "v", "uom": "box", "brand": "Other"}
    )
    data["pricing_by_inventory"]["j"] = [_tier()]

    results = get_results("p", data)

    assert [result["inventory_id"] for result in results] == ["j", "i"]


def test_buyer_message_says_price_on_quotation_and_has_no_digits_from_price():
    [offer] = get_results("p", _data([_tier(unit_price=123456, price_status="unverified")]))

    reply, options = format_results("Exam gloves", [offer])

    assert PRICE_ON_QUOTATION in reply
    assert "123" not in reply and "UGX" not in reply
    assert options[0]["default_price"] is None


def test_buyer_message_shows_range_for_verified_prices():
    [offer] = get_results("p", _data([_tier(), _tier(min_qty=10, unit_price=900)]))

    reply, _ = format_results("Exam gloves", [offer])

    assert "UGX 900 - UGX 1,000" in reply
    assert PRICE_ON_QUOTATION not in reply


def _run_price_step(monkeypatch, default_price):
    replies = []

    async def fake_send(to, text):
        replies.append(text)
        return True

    monkeypatch.setattr(whatsapp_service, "send_whatsapp_message", fake_send)
    monkeypatch.setattr(whatsapp_service, "get_session", lambda sender: {
        "state": "SELECTING_PRODUCT",
        "product": {"product_id": "p", "name": "Exam gloves"},
        "options": [],
        "selected_item": {"uom": "box", "min_qty": 1, "default_price": default_price, "pricing": ([{"min_qty": 1, "max_qty": None, "unit_price": default_price, "price_status": "verified"}] if default_price else [])},
    })
    monkeypatch.setattr(whatsapp_service, "save_session", lambda sender, data: None)
    monkeypatch.setattr(whatsapp_service, "log_audit_event", lambda *args, **kwargs: None)
    asyncio.run(whatsapp_service.handle_incoming_message(
        {"from": "+256700000001", "type": "text", "text": {"body": "5"}}
    ))
    return replies[0]


def test_price_step_never_prints_a_number_for_unverified_offers(monkeypatch):
    reply = _run_price_step(monkeypatch, None)

    assert "Price on quotation" in reply
    assert "UGX" not in reply and "Estimated starting price" not in reply
    assert "1. Request quotation" in reply


def test_price_step_still_shows_verified_price(monkeypatch):
    reply = _run_price_step(monkeypatch, 34372)

    assert "Estimated starting price: UGX 34,372 per box." in reply


# ---- sync, storage and cache ------------------------------------------------

@pytest.fixture
def session():
    engine = create_engine("sqlite:///:memory:")
    models.Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    try:
        yield db
    finally:
        db.close()


def _snapshot(price_status=None):
    pricing = {"pricing_id": "pr1", "inventory_id": "i1", "min_qty": 1, "unit_price": 1500}
    if price_status is not None:
        pricing["price_status"] = price_status
    return {
        "products": [{"product_id": "p1", "name": "Gloves", "category": "Consumables"}],
        "vendors": [{"vendor_id": "v1", "name": "Supplier"}],
        "inventory": [{"inventory_id": "i1", "product_id": "p1", "vendor_id": "v1", "uom": "box"}],
        "pricing": [pricing],
        "aliases": [],
    }


def test_sync_defaults_to_unverified_when_the_sheet_has_no_status_column(session):
    from sync_sheets_to_db import sync_catalog_snapshot

    sync_catalog_snapshot(session, _snapshot())

    assert session.get(models.Pricing, "pr1").price_status == "unverified"


def test_sync_verifies_and_unverifies_with_the_sheet(session):
    from sync_sheets_to_db import sync_catalog_snapshot

    sync_catalog_snapshot(session, _snapshot("Verified"))
    assert session.get(models.Pricing, "pr1").price_status == "verified"

    second = sync_catalog_snapshot(session, _snapshot("yes"))  # anything but the exact word revokes
    assert session.get(models.Pricing, "pr1").price_status == "unverified"
    assert second.summary["pricing"]["changed"] == 1


def test_unchanged_verified_row_is_not_reported_as_changed(session):
    from sync_sheets_to_db import sync_catalog_snapshot

    sync_catalog_snapshot(session, _snapshot("verified"))
    again = sync_catalog_snapshot(session, _snapshot("verified"))

    assert again.summary["pricing"]["unchanged"] == 1


def test_price_status_is_exposed_by_load_data_and_json_safe(monkeypatch, session):
    session.add_all([
        models.Vendor(vendor_id="v", name="n"),
        models.Product(product_id="p", name="x"),
        models.Inventory(inventory_id="i", product_id="p", vendor_id="v"),
        models.Pricing(pricing_id="pr", inventory_id="i", min_qty=1, unit_price=5,
                       price_status="verified", price_valid_until=date(2026, 12, 1)),
        models.TaxonomyVersion(version_id="v1", name="t", status="active",
                               effective_date=date(2026, 9, 1), activated_at=datetime(2026, 9, 2)),
    ])
    session.commit()
    monkeypatch.setattr(models, "SessionLocal", lambda: session)
    monkeypatch.setattr(session, "close", lambda: None)

    data = models.load_data()

    # Previously a date value made json.dumps raise, silently disabling the Redis cache.
    payload = json.loads(json.dumps(data))
    assert payload["pricing"][0]["price_status"] == "verified"
    assert payload["pricing"][0]["price_valid_until"] == "2026-12-01"
    assert is_price_displayable(payload["pricing"][0], date(2026, 11, 21))
    assert not is_price_displayable(payload["pricing"][0], date(2026, 12, 2))


# ---- catalogue lint ---------------------------------------------------------

def _lint_data(prices, statuses=None, uom="box"):
    products = [{"product_id": f"p{n}", "product_family_id": "FAM"} for n in range(len(prices))]
    inventory = [{"inventory_id": f"i{n}", "product_id": f"p{n}", "uom": uom} for n in range(len(prices))]
    pricing = [
        {"pricing_id": f"pr{n}", "inventory_id": f"i{n}", "min_qty": 1, "unit_price": price,
         "price_status": (statuses or ["verified"] * len(prices))[n]}
        for n, price in enumerate(prices)
    ]
    return {"products": products, "inventory": inventory, "pricing": pricing}


def test_lint_flags_absurd_price_spread_within_family_and_pack():
    report = lint_catalogue(_lint_data([834, 10_000_000]))

    assert report.counts["price_spread"] == 1
    assert "11,990x" in report.findings[0].message or "11,99" in report.findings[0].message


def test_lint_is_quiet_for_consistent_verified_prices():
    report = lint_catalogue(_lint_data([1000, 1200]))

    assert report.findings == []
    assert report.stats["offers_fully_verified"] == 2


def test_lint_reports_missing_ids_prices_and_orphans():
    data = _lint_data([1000])
    data["pricing"] += [
        {"pricing_id": "", "inventory_id": "i0", "min_qty": 1, "unit_price": 5},
        {"pricing_id": "pr9", "inventory_id": "ghost", "min_qty": 1, "unit_price": 5},
        {"pricing_id": "pr10", "inventory_id": "i0", "min_qty": 5, "unit_price": None},
    ]

    codes = lint_catalogue(data).counts

    assert codes["missing_pricing_id"] == 1
    assert codes["orphan_pricing"] == 1
    assert codes["missing_price"] == 1
    assert lint_catalogue(data).has_errors


def test_lint_warns_when_nothing_is_verified_and_on_partial_verification():
    assert lint_catalogue(_lint_data([1000], ["unverified"])).counts["no_verified_prices"] == 1
    data = _lint_data([1000])
    data["pricing"].append({"pricing_id": "x", "inventory_id": "i0", "min_qty": 10, "unit_price": 900, "price_status": "unverified"})
    assert lint_catalogue(data).counts["partially_verified"] == 1


def test_lint_flags_prices_that_rise_with_quantity_and_expired_verification():
    data = _lint_data([1000])
    data["pricing"].append({"pricing_id": "x", "inventory_id": "i0", "min_qty": 10, "unit_price": 1500, "price_status": "verified"})
    assert lint_catalogue(data).counts["tier_price_increases"] == 1
    data = _lint_data([1000])
    data["pricing"][0]["price_valid_until"] = "2020-01-01"
    assert lint_catalogue(data, TODAY).counts["verified_but_expired"] == 1
