# SocioMed Data Blueprint

This is the refined translation of the co-founder clarifications into the current `sociomed-lean` repo.

## Confirmed Product Decision

SocioMed is staying `RFQ-first` and WhatsApp-only for buyers. SocioMed is the
medical-supply sourcing brand; Zelus Life is the sole commercial and legal
entity. Partner supplier identity and contact details are internal-only.

That means:

- The current WhatsApp flow should optimize for medical-supply sourcing, offer comparison, and quotation capture.
- We should persist leads and RFQs, not build a mandatory cart-and-order checkout flow.
- Any future "checkout" work should only happen if the business model shifts toward direct ordering.

The qualification model has exactly three buyer-facing states:

1. **Browsing / price-check** — show ranked offers and record lead/funnel activity; do not create an RFQ.
2. **RFQ** — an explicit quotation action creates exactly one RFQ with buyer name, organization, phone, product, quantity, and delivery location.
3. **PFI-eligible** — an internal generation check applied when the RFQ is created; this is not a fourth buyer-facing state.

Budget, tender, and urgency language is not classified automatically.

## What Is Already Aligned

The repo already uses the "Clean 5" catalog structure:

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
2. Expanded catalog fields
   The data model now supports `vendors.email`, `vendors.region`, and `inventory.uom`.
3. UoM-first offer display
   Catalog and WhatsApp offer messages now include `uom`, so the buyer sees "Box of 100" instead of a vague unit price.
4. Range-first pricing display
   Offer summaries now show a real price range when quantity tiers exist.
5. Vendor phone quality visibility
   The sync step now reports how many vendor numbers are valid, missing, or not in `+countrycode` format.
6. Deterministic offer ranking and safe visibility
   In-stock Zelus-owned inventory ranks first unless an in-stock partner is more than 10% cheaper. Out-of-stock owned inventory does not outrank available partner stock. WhatsApp shows at most three offers and never shows vendor identity, vendor contact details, exact stock quantity, cost, commission, margin, or ownership type.
7. PFI approval workflow
   `rfq_requests.pfi_status` is separate from the six-value RFQ lifecycle status and is one of `none`, `pending_approval`, `approved`, or `held`. A PFI is drafted only when every required RFQ field and every line-item unit price is present. Delivery remains excluded from automated totals.

## Sheet Structure To Use Now

Use these exact tabs and lowercase headers in Google Sheets:

| Tab | Required columns |
| --- | --- |
| `products` | `product_id`, `name`, `category` |
| `vendors` | `vendor_id`, `name`, `phone`, `email`, `region`, optional `commission_rate` (for example `8.5` for 8.5%), optional `is_own_inventory` (`TRUE` only for Zelus Life owned stock) |
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
5. Update stock status manually
   The founder is the source of truth for `In Stock` and `Out of Stock`; there is no scheduled or live inventory sync.

## Founder Operating Routine

- Keep using the daily WhatsApp RFQ digest as the primary overview of new RFQs, status changes, Zelus direct revenue, and estimated commission revenue.
- Treat each real-time `PFI approval required` WhatsApp alert separately from the digest. It includes the RFQ ID, buyer, organization, product summary, total, and strict reply instructions.
- Reply `YES {rfq_id}` only when that pending PFI is approved. This changes `pfi_status` to `approved` and sends the buyer a short courtesy message; the founder still downloads and forwards the PDF manually.
- Reply `NO {rfq_id}` to place the PFI on hold. The buyer is not messaged.
- Unanswered approvals remain `pending_approval`; launch has no timeout or 24-hour re-alert.
- Continue using the RFQ notes field for next actions and follow-up dates. Payment confirmation remains manual.

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

`sku` belongs on `inventory`, not `products`. The same internal SKU may appear across multiple inventory rows when different vendors or brands can satisfy the same internal reference. This lets SocioMed compare vendor offers while preserving one internal procurement reference.

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

Brand search is intentionally not automatic from `inventory.brand` yet. If `Zelus` should return gloves and oxygen masks, add `Zelus` as an alias for those product IDs. This keeps brand discovery deliberate instead of letting one broad brand query return unrelated inventory.

## Search Index Rules

Catalog search now uses a weighted index:

| Source | Weight |
| --- | --- |
| `aliases.alias` | Highest |
| `products.name` | Highest |
| `products.clinical_speciality` | Medium-high |
| `products.category` | Medium |
| `inventory.sku` | Medium |

The buyer does not see match explanations. The index is designed to help procurement heads get to relevant sourcing offers quickly, not to explain search mechanics.

## Recommendation Rules

Recommendations are driven by `products.related_ids`.

- Direct links are shown first.
- Reverse links are also supported, so if product A lists product B, product B can recommend product A.
- WhatsApp related products appear as `R1`, `R2`, `R3`.
- Selecting `R1` loads that related product into the same offer flow, preserving RFQ-first behavior.

Different brands for the same item are handled as offers under the same `product_id`. One internal product can have multiple inventory rows from different vendors and brands, while vendor identity remains hidden from the buyer.

## Clarifications That Are Compatible Without More Code

Some of the co-founder advice is primarily about data quality and operating discipline, not backend changes:

- Use brand names as aliases
- Add misspellings to `aliases`
- Prioritize consumables before complex equipment bundles
- Keep product rows clean and put sellable variants in `inventory`

Those rules are compatible with the current repo as long as the sheet is populated correctly.

## Clarifications That Are Still Phase Two

These are strong product ideas, but they are not same-day launch blockers:

1. Short-form session cart with checkout branching
   Redis already stores the user session, but there is no dedicated cart model or `Checkout` flow yet. That is intentional while we remain RFQ-first.
2. Recommendation quality scoring
   `related_ids` now supports linked-product recommendations, but there is not yet a performance-based scoring model using RFQ history or conversion data.
3. Automated PFI delivery
   The system generates the internal Zelus Life PFI draft, but it does not upload or send the PDF over WhatsApp or email. Founder approval and manual forwarding remain mandatory.
4. PFI timeouts and re-alerts
   Pending approvals remain pending indefinitely at launch.

These belong in the next product iteration after the data quality and vendor coverage issues are fixed.

## Fastest Execution Order

1. Fix the Google Sheet tabs and headers exactly.
2. Populate at least 3 vendors with real `+256...` phone numbers.
3. Add `uom` to every inventory row.
4. Add alias coverage for abbreviations, misspellings, and intentional brand terms.
5. Re-run `python3 sync_sheets_to_db.py`.
6. Add `clinical_speciality` and `related_ids` where relevant.
7. Verify `/api/catalog/search?q=gloves`, `/api/catalog/search?q=dentistry`, and a WhatsApp search flow.
