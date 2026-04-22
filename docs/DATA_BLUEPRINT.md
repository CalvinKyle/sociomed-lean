# SocioMed Data Blueprint

This is the refined translation of the co-founder clarifications into the current `sociomed-lean` repo.

## What Is Already Aligned

The repo already uses the "Clean 5" marketplace structure:

- `products`
- `vendors`
- `inventory`
- `pricing`
- `aliases`

That part of the blueprint is not a new direction. It is the right direction, and the code now leans into it more explicitly.

## What We Implemented Now

These clarifications are now reflected directly in the repo:

1. Lowercase-safe sheet sync
   `sync_sheets_to_db.py` now normalizes incoming sheet headers and strips whitespace before loading records. This is the protection against `InventoryID` versus `inventory_id` style failures.
2. Expanded marketplace fields
   The data model now supports `vendors.email`, `vendors.region`, and `inventory.uom`.
3. UoM-first offer display
   Catalog and WhatsApp offer messages now include `uom`, so the buyer sees "Box of 100" instead of a vague unit price.
4. Range-first pricing display
   Offer summaries now show a real price range when quantity tiers exist.
5. Vendor phone quality visibility
   The sync step now reports how many vendor numbers are valid, missing, or not in `+countrycode` format.

## Sheet Structure To Use Now

Use these exact tabs and lowercase headers in Google Sheets:

| Tab | Required columns |
| --- | --- |
| `products` | `product_id`, `name`, `category` |
| `vendors` | `vendor_id`, `name`, `phone`, `email`, `region` |
| `inventory` | `inventory_id`, `product_id`, `vendor_id`, `brand`, `uom`, `stock_qty`, `lead_time_days` |
| `pricing` | `pricing_id`, `inventory_id`, `min_qty`, `max_qty`, `unit_price` |
| `aliases` | `alias`, `product_id` |

## Operational Rules That Matter Before Launch

1. Seed everyday consumables first
   Start with the high-frequency procurement items that buyers reorder weekly or monthly.
2. Put real vendor phones in the sheet
   Launching without vendor phone coverage will make the RFQ notification loop look broken even if the backend is healthy.
3. Treat `pricing.unit_price` as absolute money, not a percentage
   If a kit is UGX 475,000, store `475000`.
4. Use aliases aggressively
   Add abbreviations, common misspellings, and brand terms that buyers actually type.

## Clarifications That Are Compatible Without More Code

Some of the co-founder advice is primarily about data quality and operating discipline, not backend changes:

- Use brand names as aliases
- Add misspellings to `aliases`
- Prioritize consumables before complex equipment bundles
- Keep product rows clean and put sellable variants in `inventory`

Those rules are compatible with the current repo as long as the sheet is populated correctly.

## Clarifications That Are Still Phase Two

These are strong product ideas, but they are not same-day launch blockers:

1. Multi-item request splitting
   The current WhatsApp flow routes multi-item requests into RFQ mode, but it does not yet build a full parsed multi-line cart.
2. Short-form session cart with checkout branching
   Redis already stores the user session, but there is no dedicated cart model or `Checkout` flow yet.
3. Equipment-to-consumables recommendations
   The catalog does not yet model cross-sell relationships between equipment and consumables.
4. PFI or PDF generation
   The repo does not yet generate supplier-facing PDFs.

These belong in the next product iteration after the data quality and vendor coverage issues are fixed.

## Fastest Execution Order

1. Fix the Google Sheet tabs and headers exactly.
2. Populate at least 3 vendors with real `+256...` phone numbers.
3. Add `uom` to every inventory row.
4. Add alias coverage for abbreviations, misspellings, and brand terms.
5. Re-run `python3 sync_sheets_to_db.py`.
6. Verify `/api/catalog/search?q=gloves` and a WhatsApp search flow.
7. Only then plan the multi-item cart and recommendation features.
