# app/services/search.py

from typing import Dict, List, Optional
from rapidfuzz import process

from app.core.exchange_rates import convert_result_prices

def find_products(query: str, products: List[Dict], aliases: List[Dict], limit: int = 5) -> List[Dict]:
    """Find one or more products by alias or fuzzy product name."""
    query_clean = query.lower().strip()

    matches: List[Dict] = []
    seen_product_ids = set()

    for a in aliases:
        if a["alias"].lower() in query_clean:
            match = next((p for p in products if p["product_id"] == a["product_id"]), None)
            if match and match["product_id"] not in seen_product_ids:
                matches.append(match)
                seen_product_ids.add(match["product_id"])

    names = [p["name"] for p in products]
    for _, score, index in process.extract(query, names, limit=max(limit * 2, 6)):
        if score <= 70:
            continue
        product = products[index]
        if product["product_id"] in seen_product_ids:
            continue
        matches.append(product)
        seen_product_ids.add(product["product_id"])
        if len(matches) >= limit:
            break

    return matches


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
