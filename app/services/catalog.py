from typing import Dict, List

from rapidfuzz import process

from app.core.cache import get_cached_data
from app.core.config import DEFAULT_CURRENCY
from app.services.search import find_product, get_results


def _build_offer(product: Dict, result: Dict) -> Dict:
    pricing = result.get("pricing", [])
    all_prices = [tier["unit_price"] for tier in pricing]
    return {
        "product_id": product["product_id"],
        "product_name": product["name"],
        "brand": result.get("brand", "Generic"),
        "vendor_id": result.get("vendor_id"),
        "vendor_name": result.get("vendor_name"),
        "min_qty": result.get("min_qty", 1),
        "starting_price": min(all_prices) if all_prices else result.get("default_price"),
        "max_price": max(all_prices) if all_prices else result.get("default_price"),
        "stock_qty": result.get("stock_qty", 0),
        "lead_time_days": result.get("lead_time_days"),
        "currency": DEFAULT_CURRENCY,
    }


def search_catalog(query: str, limit: int = 5) -> List[Dict]:
    data = get_cached_data()
    products = data.get("products", [])
    aliases = data.get("aliases", [])

    matches: List[Dict] = []
    seen_product_ids = set()

    exact_match = find_product(query, products, aliases)
    if exact_match:
        matches.append(exact_match)
        seen_product_ids.add(exact_match["product_id"])

    product_names = [product["name"] for product in products]
    for _, score, index in process.extract(query, product_names, limit=max(limit * 2, 6)):
        if score < 55:
            continue
        product = products[index]
        if product["product_id"] in seen_product_ids:
            continue
        matches.append(product)
        seen_product_ids.add(product["product_id"])

    offers: List[Dict] = []
    for product in matches:
        results = get_results(product["product_id"], data)
        offers.extend(_build_offer(product, result) for result in results)

    offers.sort(key=lambda offer: (offer["starting_price"] or 999999999, -(offer["stock_qty"] or 0)))
    return offers[:limit]


def get_featured_catalog(limit: int = 6) -> List[Dict]:
    data = get_cached_data()
    products_by_id = {product["product_id"]: product for product in data.get("products", [])}

    featured: List[Dict] = []
    seen_product_ids = set()

    inventory = sorted(
        data.get("inventory", []),
        key=lambda item: ((item.get("stock_qty") or 0), -(item.get("lead_time_days") or 999)),
        reverse=True,
    )

    for inventory_item in inventory:
        product_id = inventory_item.get("product_id")
        if not product_id or product_id in seen_product_ids:
            continue

        product = products_by_id.get(product_id)
        if not product:
            continue

        results = get_results(product_id, data)
        if not results:
            continue

        featured.append(_build_offer(product, results[0]))
        seen_product_ids.add(product_id)

        if len(featured) >= limit:
            break

    return featured
