from typing import Dict, List, Optional
from rapidfuzz import process
import logging

logger = logging.getLogger(__name__)

def find_product(query: str, products: List[Dict], aliases: List[Dict]) -> Optional[Dict]:
    """Find product by name or alias with fuzzy matching."""
    names = [p["name"] for p in products]
    match = process.extractOne(query, names)
    
    if match and match[1] > 70:
        return products[match[2]]
    
    for a in aliases:
        if a["alias"].lower() in query.lower():
            return next(
                (p for p in products if p["product_id"] == a["product_id"]),
                None
            )
    
    return None


def get_results(product_id: str, data: Dict) -> List[Dict]:
    """Get available options using indexed lookups (no N+1)."""
    results = []
    
    # Use indexed lookups instead of looping through all inventory
    for inv in data.get("inventory_by_product", {}).get(product_id, []):
        vendor = data.get("vendors_by_id", {}).get(inv["vendor_id"])
        
        if not vendor:
            continue
        
        # Use indexed pricing lookup
        pricing_tiers = data.get("pricing_by_inventory", {}).get(inv["inventory_id"], [])
        
        if not pricing_tiers:
            continue
        
        results.append({
            "brand": inv.get("brand", "Generic"),
            "stock": inv.get("stock_qty", 0),
            "lead_time_days": inv.get("lead_time_days", "N/A"),
            "pricing": sorted(pricing_tiers, key=lambda x: x["min_qty"]),
            "vendor_id": vendor["vendor_id"],
            "vendor_phone": vendor.get("phone")
        })
    
    return results
        if not vendor:
            continue

        pricing_tiers = attach_pricing(inv["inventory_id"], data["pricing"])

        if not pricing_tiers:
            continue

        results.append({
            "brand": inv.get("brand", "Generic"),
            "stock": inv.get("stock_qty", 0),
            "lead_time_days": inv.get("lead_time_days", "N/A"),
            "pricing": pricing_tiers,
            "vendor_id": vendor["vendor_id"],
            "vendor_phone": vendor.get("phone")
        })

    return results
