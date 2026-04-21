from app.core.currency import format_price

def group_results(results):
    grouped = {}
    for r in results:
        brand = r.get("brand", "Generic")
        grouped.setdefault(brand, []).append(r)
    return grouped


def format_pricing_tiers(tiers, currency="UGX"):
    lines = []
    for t in tiers[:3]:
        price = format_price(t["unit_price"], currency)
        if t["max_qty"]:
            lines.append(f"{t['min_qty']}-{t['max_qty']} units: {price}")
        else:
            lines.append(f"{t['min_qty']}+ units: {price}")
    return "\n".join(lines)


def format_results(product_name, results, currency="UGX"):
    if not results:
        return "No options available. Type 0 to return to the menu.", []

    grouped = group_results(results)

    msg = f"*{product_name} – Market Options*\n\n"
    option_map = []
    counter = 1

    for brand, items in grouped.items():

        all_prices = [
            tier["unit_price"]
            for item in items
            for tier in item["pricing"]
        ]

        msg += f"*{counter}. {brand}*\n"
        msg += f"{format_price(min(all_prices), currency)} – {format_price(max(all_prices), currency)}\n"

        for item in items[:2]:
            msg += format_pricing_tiers(item["pricing"], currency) + "\n"
            msg += f"Stock: {item['stock']} | Lead time: {item['lead_time_days']} days\n\n"

        option_map.append({
            "option": counter,
            "brand": brand,
            "items": items
        })

        counter += 1

    msg += (
        "Next step:\n"
        "1 → Request official quotation (PFI)\n"
        "2 → Get best-value recommendation\n"
        "3 → Refine quantity/specifications\n"
        "0 → Main menu"
    )

    return msg, option_map
