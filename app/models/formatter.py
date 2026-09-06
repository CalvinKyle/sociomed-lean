from app.core.currency import format_price
from app.core.conversation_copy import conversation_message


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
    if max_price is None or min_price == max_price:
        return format_price(min_price or 0, currency)
    return f"{format_price(min_price or 0, currency)} - {format_price(max_price or 0, currency)}"


def format_results(product_name, results, currency="UGX"):
    if not results:
        return conversation_message("results_empty"), []

    msg = conversation_message("results_header", product_name=product_name)
    option_map = []
    for counter, item in enumerate(results[:5], start=1):
        all_prices = [tier["unit_price"] for tier in item["pricing"]]
        min_price = min(all_prices) if all_prices else item.get("default_price", 0)
        max_price = max(all_prices) if all_prices else item.get("default_price", 0)
        uom = item.get("uom") or "unit"
        sku = item.get("sku")

        msg += conversation_message("result_title", counter=counter, brand=item["brand"])
        if sku:
            msg += conversation_message("result_sku", sku=sku)
        msg += conversation_message(
            "result_summary",
            uom=uom,
            price_range=format_price_range(min_price, max_price, currency),
        )
        availability = conversation_message(
            "availability_in_stock" if (item.get("stock_qty") or 0) > 0 else "availability_sourcing"
        )
        msg += conversation_message(
            "result_availability",
            min_qty=item.get("min_qty", 1),
            uom=uom,
            availability=availability,
            lead_time_days=item.get("lead_time_days", "TBC"),
        )
        msg += format_pricing_tiers(item["pricing"], currency, uom=uom) + "\n\n"

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
            "stock_qty": item.get("stock_qty", 0),
            "lead_time_days": item.get("lead_time_days"),
            "min_qty": item.get("min_qty", 1),
            "default_price": item.get("default_price"),
            "pricing": item.get("pricing", []),
        })

    msg += conversation_message("results_footer")

    return msg, option_map
