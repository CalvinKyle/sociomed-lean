# SocioMED Data Blueprint

This is the refined translation of the co-founder clarifications into the current `sociomed-lean` repo.

## Confirmed Product Decision

SocioMED is staying `RFQ-first`.

That means:

- The current WhatsApp flow should optimize for sourcing, offer comparison, and quotation capture.
- We should persist leads and RFQs, not build a mandatory cart-and-order checkout flow.
- Any future "checkout" work should only happen if the business model shifts toward direct ordering.

## What Is Already Aligned

The repo already uses the "Clean 5" marketplace structure:

- `products`
- `vendors`
- `inventory`
- `pricing`
- `aliases`

That part of the blueprint is not a new direction. It is the right direction, and the code now leans into it more explicitly.

The approved taxonomy extends the Clean 5 without replacing it:

- `product_classes` and `product_families` define one primary buyer-facing hierarchy.
- `clinical_specialties` and `product_specialties` provide many-to-many clinical placement.
- `product_attributes` stores variant facts such as size, gauge, lumen, material, and length.
- `taxonomy_versions`, `taxonomy_version_families`, and `product_taxonomy_assignments` preserve review history and rollback.
- `product_families.emdn_code` and `product_families.gmdn_code` hold optional external nomenclature references.

Only a completely approved version can become active. Until then, runtime search continues using the legacy product fields.

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
| `vendors` | `vendor_id`, `name`, `phone`, `email`, `region`, optional `commission_rate` (for example `8.5` for 8.5%), optional `is_own_inventory` (`TRUE` only for Zelus Life owned stock) |
| `inventory` | `inventory_id`, `product_id`, `vendor_id`, `brand`, `uom`, `stock_qty`, `lead_time_days` |
| `pricing` | `pricing_id`, `inventory_id`, `min_qty`, `max_qty`, `unit_price` |
| `aliases` | `alias`, `product_id` |

The sync also recognizes these optional normalized taxonomy tabs after the family-first review is complete:

| Tab | Required columns |
| --- | --- |
| `taxonomy_versions` | `version_id`, `name`, `status` |
| `product_classes` | `class_id`, `name`, `approval_status` |
| `product_families` | `family_id`, `name`, `class_id`, `approval_status`; optional `emdn_code`, `gmdn_code` |
| `taxonomy_version_families` | `version_id`, `family_id` |
| `product_taxonomy_assignments` | `version_id`, `product_id`, `family_id`, `approval_status` |
| `clinical_specialties` | `specialty_code`, `name`; optional `active` |
| `product_specialties` | `version_id`, `product_id`, `specialty_code`, `is_primary`, `approval_status` |
| `product_attributes` | `version_id`, `product_id`, `attribute_code`, `value`, `approval_status`; optional `unit` |

## Operational Rules That Matter Before Launch

1. Seed everyday consumables first
   Start with the high-frequency procurement items that buyers reorder weekly or monthly.
2. Put real vendor phones in the sheet
   Launching without vendor phone coverage will make the RFQ notification loop look broken even if the backend is healthy.
3. Treat `pricing.unit_price` as absolute money, not a percentage
   If a kit is UGX 475,000, store `475000`.
4. Use aliases aggressively
   Add abbreviations, common misspellings, and brand terms that buyers actually type.

## Optional Product Columns Now Supported

The `products` tab may also include these optional lowercase headers:

| Column | Purpose | Example |
| --- | --- | --- |
| `clinical_speciality` | Helps specialty-led search such as dentistry, nephrology, surgery, ICU | `dentistry | surgery` |
| `related_ids` | Ordered recommendation links to other product IDs | `P-REAGENT-1 | P-REAGENT-2` |

Use `|` as the preferred separator for multi-value cells. The sync script also accepts commas and semicolons, then normalizes values to ` | ` internally.

For `related_ids`, order matters. Put the strongest recommendation first. Example: if a machine is most commonly bought with a specific reagent, list that reagent ID before secondary consumables.

The `inventory` tab may also include this optional lowercase header:

| Column | Purpose | Example |
| --- | --- | --- |
| `sku` | Internal inventory-level reference shared across vendor or brand rows for the same sellable item | `SM-GLOVE-NITRILE-M` |

`sku` belongs on `inventory`, not `products`. The same internal SKU may appear across multiple inventory rows when different vendors or brands can satisfy the same internal reference. This lets SocioMED compare vendor offers while preserving one internal procurement reference.

## Alias Rules

The `aliases` tab still maps search terms to products, but a single alias cell can now contain multiple values:

| alias | product_id |
| --- | --- |
| `IV set | infusion set | giving set` | `P-IV-SET` |

Use aliases for:

- Common buyer terms
- Abbreviations
- Misspellings
- Brand names only when you intentionally want that brand term to return the mapped product

Inventory brand and SKU are searchable automatically. Add an alias when a regional name, abbreviation, misspelling, or intentional business term should map to a specific product.

## Search Index Rules

Catalog search now uses a weighted index:

| Source | Weight |
| --- | --- |
| `aliases.alias` | Highest |
| `products.name` | Highest |
| `products.product_family_name` | High |
| `products.clinical_speciality` | Medium-high |
| Active `product_attributes` | Medium-high |
| `products.product_family_id` | Medium |
| `inventory.brand` | Medium |
| `products.category` | Medium |
| `inventory.sku` | Medium |

The buyer does not see match explanations. The index is designed to help procurement heads get to relevant supplier offers quickly, not to explain search mechanics.

## Recommendation Rules

Recommendations are driven by `products.related_ids`.

- Direct links are shown first.
- Reverse links are also supported, so if product A lists product B, product B can recommend product A.
- WhatsApp related products appear as `R1`, `R2`, `R3`.
- Selecting `R1` loads that related product into the same supplier-offer flow, preserving RFQ-first behavior.

Different brands for the same item are already handled as supplier offers under the same `product_id`. In other words, one internal product can have multiple inventory rows from different vendors and brands, and the buyer compares them before submitting an RFQ.

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
   Redis already stores the user session, but there is no dedicated cart model or `Checkout` flow yet. That is intentional while we remain RFQ-first.
3. Recommendation quality scoring
   `related_ids` now supports linked-product recommendations, but there is not yet a performance-based scoring model using RFQ history or conversion data.
4. PFI or PDF generation
   The repo does not yet generate supplier-facing PDFs.

These belong in the next product iteration after the data quality and vendor coverage issues are fixed.

## Fastest Execution Order

1. Fix the Google Sheet tabs and headers exactly.
2. Populate at least 3 vendors with real `+256...` phone numbers.
3. Add `uom` to every inventory row.
4. Add alias coverage for abbreviations, misspellings, and intentional brand terms.
5. Re-run `python3 sync_sheets_to_db.py`.
6. Add `clinical_speciality` and `related_ids` where relevant.
7. Verify `/api/catalog/search?q=gloves`, `/api/catalog/search?q=dentistry`, and a WhatsApp search flow.
