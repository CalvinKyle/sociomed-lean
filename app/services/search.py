import re
from typing import Dict, List, Optional

from rapidfuzz import fuzz

from app.core.exchange_rates import convert_result_prices
from app.core.sheet_sync import split_multi_value_cell


SEARCH_MATCH_THRESHOLD = 62
PLURAL_NORMALIZATIONS = {
    "catheters": "catheter",
    "devices": "device",
    "gloves": "glove",
    "masks": "mask",
    "needles": "needle",
    "sets": "set",
    "sutures": "suture",
    "syringes": "syringe",
}
FAMILY_DISPLAY_NAMES = {
    "SUTURE-CHROMIC-CATGUT": "Chromic catgut sutures",
    "SUTURE-NYLON": "Nylon sutures",
    "SUTURE-PDO": "PDO sutures",
    "SUTURE-PGA": "PGA sutures",
    "SUTURE-PGA-RAPID": "PGA Rapid sutures",
    "SUTURE-PGCL": "PGCL sutures",
    "SUTURE-PGLA": "PGLA sutures",
    "SUTURE-POLYGLACTIN-910": "Polyglactin 910 sutures",
    "SUTURE-POLYPROPYLENE": "Polypropylene sutures",
    "SUTURE-SILK": "Silk sutures",
}


def _normalize_search_text(value: object) -> str:
    normalized = re.sub(r"[^a-z0-9]+", " ", str(value or "").casefold())
    tokens = [PLURAL_NORMALIZATIONS.get(token, token) for token in normalized.split()]
    return " ".join(tokens)


def _score_field(query: str, value: str, weight: float) -> float:
    value_clean = _normalize_search_text(value)
    if not value_clean:
        return 0
    if query == value_clean:
        return 120 * weight
    if len(query) >= 3 and (query in value_clean or value_clean in query):
        return 105 * weight
    return max(fuzz.WRatio(query, value_clean), fuzz.token_set_ratio(query, value_clean)) * weight


def _build_search_documents(products: List[Dict], aliases: List[Dict], inventory: Optional[List[Dict]] = None) -> list[dict]:
    aliases_by_product = {}
    for alias in aliases:
        product_id = alias.get("product_id")
        alias_values = split_multi_value_cell(alias.get("alias"))
        if product_id and alias_values:
            aliases_by_product.setdefault(product_id, []).extend(alias_values)

    skus_by_product = {}
    brands_by_product = {}
    for inventory_item in inventory or []:
        product_id = inventory_item.get("product_id")
        sku = inventory_item.get("sku")
        if product_id and sku:
            skus_by_product.setdefault(product_id, []).append(sku)
        brand = inventory_item.get("brand")
        if product_id and brand:
            brands_by_product.setdefault(product_id, []).append(brand)

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
                    {"name": "product_family_name", "weight": 1.1, "values": [product.get("product_family_name", "")]},
                    {"name": "product_family_id", "weight": 0.9, "values": [product.get("product_family_id", "")]},
                    {"name": "brand", "weight": 0.85, "values": brands_by_product.get(product_id, [])},
                    {"name": "sku", "weight": 0.8, "values": skus_by_product.get(product_id, [])},
                ],
            }
        )
    return documents


def _is_positive_price(value: object) -> bool:
    try:
        return float(str(value).replace(",", "").strip()) > 0
    except (TypeError, ValueError):
        return False


def _live_offer_count(product_id: str, data: Optional[Dict]) -> int:
    if not data:
        return 0

    inventory_by_product = data.get("inventory_by_product")
    pricing_by_inventory = data.get("pricing_by_inventory")
    if inventory_by_product is not None and pricing_by_inventory is not None:
        return sum(
            1
            for inventory_item in inventory_by_product.get(product_id, [])
            if any(
                _is_positive_price(price.get("unit_price"))
                for price in pricing_by_inventory.get(inventory_item.get("inventory_id"), [])
            )
        )

    inventory_ids = {
        item.get("inventory_id")
        for item in data.get("inventory", [])
        if item.get("product_id") == product_id
    }
    return len(
        {
            price.get("inventory_id")
            for price in data.get("pricing", [])
            if price.get("inventory_id") in inventory_ids and _is_positive_price(price.get("unit_price"))
        }
    )


def _search_family_key(product: Dict) -> str:
    family_id = _normalize_search_text(product.get("product_family_id"))
    if family_id:
        return family_id
    product_name = _normalize_search_text(product.get("name"))
    return product_name or str(product.get("product_id", ""))


def find_products(
    query: str,
    products: List[Dict],
    aliases: List[Dict],
    limit: int = 5,
    data: Optional[Dict] = None,
) -> List[Dict]:
    """Find products through the weighted catalog index."""
    query_clean = _normalize_search_text(query)
    if not query_clean:
        return []
    products_by_id = {product["product_id"]: product for product in products}
    search_documents = (data or {}).get("search_documents") or _build_search_documents(
        products,
        aliases,
        (data or {}).get("inventory", []),
    )

    best_by_family: dict[str, tuple[float, int, Dict]] = {}
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

        if best_score < SEARCH_MATCH_THRESHOLD:
            continue

        offer_count = _live_offer_count(product_id, data)
        family_key = _search_family_key(product)
        candidate = (best_score, offer_count, product)
        previous = best_by_family.get(family_key)
        # Within one family, a result the buyer can actually price is more useful
        # than a slightly closer name-only row with no live offer.
        candidate_quality = (offer_count > 0, best_score, offer_count)
        previous_quality = (previous[1] > 0, previous[0], previous[1]) if previous else None
        if (
            previous is None
            or candidate_quality > previous_quality
            or (
                candidate_quality == previous_quality
                and str(product_id) < str(previous[2].get("product_id", ""))
            )
        ):
            best_by_family[family_key] = candidate

    scored_matches = list(best_by_family.values())
    scored_matches.sort(
        key=lambda match: (
            -match[0],
            -match[1],
            str(match[2].get("name", "")).casefold(),
            str(match[2].get("product_id", "")),
        )
    )

    matches = []
    for _, _, product in scored_matches[:limit]:
        display_name = str(product.get("product_family_name") or "").strip()
        if not display_name:
            display_name = FAMILY_DISPLAY_NAMES.get(str(product.get("product_family_id", "")).upper())
        if display_name:
            product = {**product, "search_display_name": display_name}
        matches.append(product)
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
            "sku": inv.get("sku"),
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
