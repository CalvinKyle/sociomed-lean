from app.core.currency import format_price


MAX_VISIBLE_OFFERS = 3
OFFER_VALIDITY_DAYS = 30
OFFER_OVERFLOW_LINE = "Reply MORE to talk to our sales team about other options"


def format_pricing_tiers(tiers, currency="UGX", uom="unit"):
    lines = []
    for t in tiers[:3]:
        price = format_price(t["unit_price"], currency)
        if t["max_qty"]:
            lines.append(f"{t['min_qty']}-{t['max_qty']} {uom}: {price}")
        else:
            lines.append(f"{t['min_qty']}+ {uom}: {price}")
    return "\n".join(lines)


def format_price_range(min_price, max_price, currency="UGX"):
    if min_price is None:
        return "Price on request"
    if max_price is None or min_price == max_price:
        return format_price(min_price, currency)
    return f"{format_price(min_price, currency)} - {format_price(max_price, currency)}"


def format_results(product_name, results, currency="UGX"):
    if not results:
        return "No options available. Type 0 to return to the menu.", []

    msg = (
        f"*{product_name} – Available Offers*\n\n"
        "Reply with the offer number you want to request.\n\n"
    )
    option_map = []
    for counter, item in enumerate(results[:MAX_VISIBLE_OFFERS], start=1):
        all_prices = [
            tier.get("unit_price")
            for tier in item.get("pricing", [])
            if tier.get("unit_price") is not None
        ]
        min_price = min(all_prices) if all_prices else item.get("default_price")
        max_price = max(all_prices) if all_prices else item.get("default_price")
        uom = item.get("uom") or "unit"
        sku = item.get("sku")
        stock_status = "In Stock" if (item.get("stock_qty") or 0) > 0 else "Out of Stock"

        msg += f"*{counter}. {item['brand']}*\n"
        msg += f"UoM: {uom} | Unit price: {format_price_range(min_price, max_price, currency)}\n"
        msg += f"Stock: {stock_status} | Lead time: {item.get('lead_time_days', 'N/A')} days\n"
        msg += f"Offer validity: {OFFER_VALIDITY_DAYS} days\n"
        pricing_text = format_pricing_tiers(item.get("pricing", []), currency, uom=uom)
        if pricing_text:
            msg += pricing_text + "\n"
        msg += "\n"

        option_map.append({
            "option": counter,
            "brand": item.get("brand", "Generic"),
            "sku": sku,
            "uom": uom,
            "inventory_id": item.get("inventory_id"),
            "product_id": item.get("product_id"),
            "vendor_id": item.get("vendor_id"),
            "vendor_name": item.get("vendor_name"),
            "vendor_phone": item.get("vendor_phone"),
            "is_own_inventory": bool(item.get("is_own_inventory")),
            "stock_qty": item.get("stock_qty", 0),
            "lead_time_days": item.get("lead_time_days"),
            "min_qty": item.get("min_qty", 1),
            "default_price": item.get("default_price"),
            "pricing": item.get("pricing", []),
        })

    msg += f"{OFFER_OVERFLOW_LINE}\n0 → Main menu"

    return msg, option_map
