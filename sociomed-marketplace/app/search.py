from rapidfuzz import process


def find_product(query, products, aliases):
    names = [p["name"] for p in products]

    match = process.extractOne(query, names)
    if match and match[1] > 70:
        return products[match[2]]

    for a in aliases:
        if a["alias"].lower() in query.lower():
            return next(p for p in products if p["product_id"] == a["product_id"])

    return None


def attach_pricing(inventory_id, pricing_table):
    tiers = [p for p in pricing_table if p["inventory_id"] == inventory_id]
    return sorted(tiers, key=lambda x: x["min_qty"])


def get_results(product_id, data):
    results = []

    for inv in data["inventory"]:
        if inv["product_id"] == product_id:

            vendor = next(v for v in data["vendors"] if v["vendor_id"] == inv["vendor_id"])

            pricing_tiers = attach_pricing(inv["inventory_id"], data["pricing"])

            results.append({
                "brand": inv.get("brand", "Generic"),
                "stock": inv["stock_qty"],
                "lead_time_days": inv.get("lead_time_days", "N/A"),
                "pricing": pricing_tiers,
                "vendor_id": vendor["vendor_id"],
                "vendor_phone": vendor.get("phone")
            })

    return results
