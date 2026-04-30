# app/services/search.py

from typing import Dict, List, Optional
from rapidfuzz import fuzz

from app.core.exchange_rates import convert_result_prices
from app.core.sheet_sync import split_multi_value_cell


def _score_field(query: str, value: str, weight: float) -> float:
    value_clean = str(value or "").lower().strip()
    if not value_clean:
        return 0
    if query == value_clean:
        return 120 * weight
    if query in value_clean or value_clean in query:
        return 105 * weight
    return fuzz.WRatio(query, value_clean) * weight


def _build_search_documents(products: List[Dict], aliases: List[Dict]) -> list[dict]:
    aliases_by_product = {}
    for alias in aliases:
        product_id = alias.get("product_id")
        alias_text = alias.get("alias")
        if product_id and alias_text:
            aliases_by_product.setdefault(product_id, []).append(alias_text)

    documents = []
    for product in products:
        product_id = product.get("product_id")
        documents.append(
            {
                "product_id": product_id,
                "fields": [
                    {"name": "alias", "weight": 1.25, "values": aliases_by_product.get(product_id, [])},
                    {"name": "name", "weight": 1.15, "values": [product.get("name", "")]},
                    {"name": "clinical_speciality", "weight": 0.95, "values": split_multi_value_cell(product.get("clinical_speciality"))},
                    {"name": "category", "weight": 0.75, "values": [product.get("category", "")]},
                ],
            }
        )
    return documents


def find_products(
    query: str,
    products: List[Dict],
    aliases: List[Dict],
    limit: int = 5,
    data: Optional[Dict] = None,
) -> List[Dict]:
    """Find products through the weighted catalog index."""
    query_clean = query.lower().strip()
    products_by_id = {product["product_id"]: product for product in products}
    search_documents = (data or {}).get("search_documents") or _build_search_documents(products, aliases)

    scored_matches = []
    for document in search_documents:
        product_id = document.get("product_id")
        product = products_by_id.get(product_id)
        if not product:
            continue

        best_score = 0
        for field in document.get("fields", []):
            field_score = max(
                (_score_field(query_clean, value, field.get("weight", 1)) for value in field.get("values", [])),
                default=0,
            )
            best_score = max(best_score, field_score)

        if best_score >= 58:
            scored_matches.append((best_score, product))

    scored_matches.sort(key=lambda match: (-match[0], str(match[1].get("name", "")).lower()))

    return [product for _, product in scored_matches[:limit]]


def find_product(query: str, products: List[Dict], aliases: List[Dict]) -> Optional[Dict]:
    matches = find_products(query, products, aliases, limit=1)
    return matches[0] if matches else None


def get_results(product_id: str, data: Dict, currency: str = "UGX") -> List[Dict]:
    """
    Get all available vendor options for a product with prices in buyer's currency.
    
    Args:
        product_id: Product to search for
        data: Cached data with pre-built indexes
        currency: Target currency for price conversion (detected from buyer's phone)
    
    Returns:
        List of results with prices converted to buyer's currency
    """
    results = []
    
    inventory_items = data.get("inventory_by_product", {}).get(product_id, [])
    
    for inv in inventory_items:
        vendor = data.get("vendors_by_id", {}).get(inv["vendor_id"])
        if not vendor:
            continue
        
        pricing_tiers = data.get("pricing_by_inventory", {}).get(inv["inventory_id"], [])
        if not pricing_tiers:
            continue

        # Pricing tiers are in base currency (UGX) from Google Sheets
        pricing_tiers = sorted(pricing_tiers, key=lambda x: x["min_qty"])
        first_tier = pricing_tiers[0]
        
        result = {
            "inventory_id": inv.get("inventory_id"),
            "product_id": product_id,
            "brand": inv.get("brand", "Generic"),
            "uom": inv.get("uom") or "unit",
            "stock_qty": inv.get("stock_qty", 0),
            "lead_time_days": inv.get("lead_time_days", "N/A"),
            "pricing": pricing_tiers,  # Still in base currency
            "min_qty": first_tier.get("min_qty", 1),
            "default_price": first_tier.get("unit_price"),  # Still in base currency
            "vendor_id": vendor["vendor_id"],
            "vendor_phone": vendor.get("phone"),
            "vendor_name": vendor.get("name", ""),
        }
        
        # Convert prices to buyer's currency
        result = convert_result_prices(result, currency)
        
        results.append(result)
    
    # Sort by lowest entry price (now in buyer's currency)
    results.sort(key=lambda r: r["pricing"][0]["unit_price"] if r["pricing"] else 999999)
    return results
