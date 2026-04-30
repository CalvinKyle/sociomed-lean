# app/services/catalog.py

from typing import Dict, List

from app.core.cache import get_cached_data
from app.core.config import DEFAULT_CURRENCY
from app.services.search import find_products, get_results


def _build_offer(product: Dict, result: Dict, currency: str = DEFAULT_CURRENCY) -> Dict:
    """
    Build a catalog offer from search result.
    Prices are already converted by get_results(), just extract them.
    """
    pricing = result.get("pricing", [])
    all_prices = [tier["unit_price"] for tier in pricing]
    return {
        "product_id": product["product_id"],
        "product_name": product["name"],
        "brand": result.get("brand", "Generic"),
        "sku": result.get("sku"),
        "uom": result.get("uom"),
        "vendor_id": result.get("vendor_id"),
        "vendor_name": result.get("vendor_name"),
        "min_qty": result.get("min_qty", 1),
        "starting_price": min(all_prices) if all_prices else result.get("default_price"),
        "max_price": max(all_prices) if all_prices else result.get("default_price"),
        "stock_qty": result.get("stock_qty", 0),
        "lead_time_days": result.get("lead_time_days"),
        "currency": currency,  # Always set to buyer's detected currency
    }


def search_catalog(query: str, limit: int = 5, currency: str = DEFAULT_CURRENCY) -> List[Dict]:
    """
    Search catalog and return offers in buyer's currency.
    
    Args:
        query: Search term from buyer
        limit: Max results to return
        currency: Buyer's currency (detected from phone or IP)
    """
    data = get_cached_data()
    products = data.get("products", [])
    aliases = data.get("aliases", [])

    matches: List[Dict] = []
    seen_product_ids = set()

    for matched_product in find_products(query, products, aliases, limit=limit, data=data):
        if matched_product["product_id"] in seen_product_ids:
            continue
        matches.append(matched_product)
        seen_product_ids.add(matched_product["product_id"])

    offers: List[Dict] = []
    for product in matches:
        # get_results() now handles currency conversion internally
        results = get_results(product["product_id"], data, currency=currency)
        offers.extend(_build_offer(product, result, currency=currency) for result in results)

    offers.sort(key=lambda offer: (offer["starting_price"] or 999999999, -(offer["stock_qty"] or 0)))
    return offers[:limit]


def get_featured_catalog(limit: int = 6, currency: str = DEFAULT_CURRENCY) -> List[Dict]:
    """
    Get featured catalog offers in buyer's currency.
    
    Args:
        limit: Max featured products to return
        currency: Buyer's currency (detected from phone or IP)
    """
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

        # get_results() now handles currency conversion internally
        results = get_results(product_id, data, currency=currency)
        if not results:
            continue

        featured.append(_build_offer(product, results[0], currency=currency))
        seen_product_ids.add(product_id)

        if len(featured) >= limit:
            break

    return featured


def get_related_catalog(product_id: str, limit: int = 4, currency: str = DEFAULT_CURRENCY) -> List[Dict]:
    """Return live offers for products linked through products.related_ids."""
    data = get_cached_data()
    products_by_id = data.get("products_by_id") or {product["product_id"]: product for product in data.get("products", [])}

    related_ids = []
    seen_ids = {product_id}
    for candidate_id in data.get("related_by_product", {}).get(product_id, []):
        if candidate_id not in seen_ids:
            related_ids.append(candidate_id)
            seen_ids.add(candidate_id)
    for candidate_id in data.get("reverse_related_by_product", {}).get(product_id, []):
        if candidate_id not in seen_ids:
            related_ids.append(candidate_id)
            seen_ids.add(candidate_id)

    recommendations: List[Dict] = []
    for related_id in related_ids:
        product = products_by_id.get(related_id)
        if not product:
            continue

        results = get_results(related_id, data, currency=currency)
        if not results:
            continue

        recommendations.append(_build_offer(product, results[0], currency=currency))
        if len(recommendations) >= limit:
            break

    return recommendations
