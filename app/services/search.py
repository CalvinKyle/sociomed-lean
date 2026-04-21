from typing import Dict, List, Optional
from rapidfuzz import process
import logging

logger = logging.getLogger(__name__)

def find_product(query: str, products: List[Dict], aliases: List[Dict]) -> Optional[Dict]:
    """Find product by name or alias with fuzzy matching."""
    query_clean = query.lower().strip()
    
    # Check aliases first (exact match preferred)
    for a in aliases:
        if a["alias"].lower() in query_clean:
            match = next((p for p in products if p["product_id"] == a["product_id"]), None)
            if match:
                return match
    
    # Fuzzy match on product names
    names = [p["name"] for p in products]
    result = process.extractOne(query, names)
    
    if result and result[1] > 70:
        return products[result[2]]
    
    return None


def get_results(product_id: str, data: Dict) -> List[Dict]:
    """Get all available vendor options for a product. Uses pre-built indexes — O(1) lookups."""
    results = []
    
    inventory_items = data.get("inventory_by_product", {}).get(product_id, [])
    
    for inv in inventory_items:
        vendor = data.get("vendors_by_id", {}).get(inv["vendor_id"])
        if not vendor:
            continue
        
        pricing_tiers = data.get("pricing_by_inventory", {}).get(inv["inventory_id"], [])
        if not pricing_tiers:
            continue

        pricing_tiers = sorted(pricing_tiers, key=lambda x: x["min_qty"])
        first_tier = pricing_tiers[0]
        
        results.append({
            "inventory_id": inv.get("inventory_id"),
            "product_id": product_id,
            "brand": inv.get("brand", "Generic"),
            "stock_qty": inv.get("stock_qty", 0),
            "lead_time_days": inv.get("lead_time_days", "N/A"),
            "pricing": pricing_tiers,
            "min_qty": first_tier.get("min_qty", 1),
            "default_price": first_tier.get("unit_price"),
            "vendor_id": vendor["vendor_id"],
            "vendor_phone": vendor.get("phone"),
            "vendor_name": vendor.get("name", ""),
        })
    
    # Sort by lowest entry price so the best deal surfaces first
    results.sort(key=lambda r: r["pricing"][0]["unit_price"] if r["pricing"] else 999999)
    return results
