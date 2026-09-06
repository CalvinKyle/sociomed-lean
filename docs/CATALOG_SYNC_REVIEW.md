# Catalog and PostgreSQL sync review

Review basis: `sociomed_db-2.xlsx` compared with the current application models, search index, Google Sheets adapter, and `sync_sheets_to_db.py` on 2026-09-06. The original workbook was not changed.

## Refined workbook result

The output workbook keeps the five live import tabs (`products`, `vendors`, `inventory`, `pricing`, `aliases`) and adds two non-imported review tabs (`pricing_exceptions`, `sync_review`).

| Area | Refined result |
|---|---:|
| Product rows retained | 1,715 |
| Inventory rows retained | 1,715 |
| Valid pricing rows in the live `pricing` tab | 4,461 |
| Unsafe pricing rows preserved in `pricing_exceptions` | 818 |
| Stable pricing IDs generated for otherwise valid rows | 143 |
| Misplaced pricing notes moved out of the validity-date column | 5,025 |
| Suture alias rows generated | 116 |
| Suture subcategories standardized | 98 |
| Product family IDs populated | 1,715 |
| Equipment review flags populated | 1,071 |

The refined workbook fixes the malformed vendor header, renames the pricing validity header to the field the code imports, explicitly names the inventory manufacturer/classification columns, and retains every rejected pricing row with its source row and reason.

## Original workbook risks found

| Priority | Finding | Product impact |
|---|---|---|
| P0 | 740 pricing rows referenced inventory IDs absent from the inventory tab | Prices could never appear in buyer results |
| P0 | 78 pricing rows had no usable positive unit price | The app would create zero-price rows or silently skip useful offers |
| P0 | 223 pricing rows had no `pricing_id`; 145 of those otherwise had a usable price | Valid offers were skipped by the upsert loop |
| P0 | The pricing sheet used `valid_to` while code imported `price_valid_until`; 5,025 notes occupied that column | Sync could attempt to parse notes as ISO dates and roll back |
| P0 | Vendor column P combined `is_own_inventory` and `commission_rate` into one header | Neither field mapped reliably |
| P1 | All 221 original alias cells were blank | Alias replacement would erase all aliases and add none |
| P1 | 221 inventory rows lacked UOM; 1,490 lacked stock quantity; 1,459 lacked lead time | Buyer wording could imply false stock or timing certainty |
| P1 | 37 of 41 vendors lacked phone numbers; 36 lacked email; 38 lacked region | Supplier notification and fallback routing coverage is low |
| P1 | Suture taxonomy used `Sutures`, `Sutures & Ligatures`, and `Sutures | Ligatures` | Category browse and reporting fragment the same family |
| P2 | 121 products lacked subcategory and 1,683 lacked an active flag | Filtering and lifecycle control are incomplete |

## What the current code imports

| Workbook tab | Imported fields | Present but currently ignored |
|---|---|---|
| `products` | `product_id`, `name`, `category`, `clinical_speciality`, `related_ids`, `product_family_id`, `equipment_review_required` | `subcategory`, `description`, `standard_uom`, `manufacturer`, `regulatory_class`, `search_tags`, `primary_application`, `buyer_type`, `active` |
| `vendors` | `vendor_id`, `name`, `phone`, `email`, `region`, `commission_rate`, `is_own_inventory` | `vendor_type`, `address`, `country`, `contact_person`, `delivery_terms`, `payment_terms`, `lead_time_days`, `active`, `notes` |
| `inventory` | `inventory_id`, `product_id`, `vendor_id`, `brand`, `uom`, `stock_qty`, `lead_time_days`, `sku` if present | `stock_status`, `min_order_qty`, `manufacturer`, `country_of_origin`, `classification`, `active` |
| `pricing` | `pricing_id`, `inventory_id`, `min_qty`, `max_qty`, `unit_price`, `price_valid_until` | `currency`, `price_type`, `valid_from`, `notes` |
| `aliases` | `alias`, `product_id`; pipe/comma/semicolon values are split into separate database aliases | `alias_type`, `language`, `source` |
| Other tabs | Nothing | `customers`, `rfq_requests`, `categories`, and `buyer_leads` are not part of the catalog sync |

## Reliability changes implemented in code

The sync now validates the complete normalized snapshot before opening the database transaction. It rejects blank required row values, duplicate primary keys, orphan product/vendor/inventory references, nonnumeric or nonpositive pricing, and invalid quantity ranges. A bad Sheet therefore fails before PostgreSQL is partially changed.

Blank `stock_qty` and `lead_time_days` are now stored as unknown (`NULL`) rather than confirmed zero. Alias replacement remains transactional and the refined sheet supplies real aliases, so a failed sync rolls back.

Search now normalizes selected plurals, splits multi-value aliases, searches brand and family ID, deduplicates the shortlist by product family, and prefers a representative with validated pricing. Cache and live search now share one search-document builder, preventing their logic from drifting.

## Recommended rollout within Render free-tier limits

1. Upload only the refined workbook's five live tabs to the Google Sheet used by `SHEET_NAME`. Keep the original Google Sheet or workbook as a rollback copy.
2. Review and correct `pricing_exceptions`, especially any records that represent real inventory and should return to the live `pricing` tab.
3. Add supplier phone numbers in E.164 format (`+countrycode...`) for every vendor expected to receive RFQs. Four callable vendors is enough for a controlled beta, not broad routing.
4. From a trusted local machine or a manual GitHub Actions job holding `DATABASE_URL`, `GOOGLE_CREDS_JSON`, `SHEET_NAME`, and `REDIS_URL`, run `python sync_sheets_to_db.py --dry-run` first, then run without `--dry-run` only after the validation summary is clean.
5. Keep `RUN_DB_MIGRATIONS=true` for the Render web startup. This handles Alembic on the free tier but does not import Google Sheet data; catalog sync remains a separate deliberate operation.
6. Test `sutures`, one exact suture material/brand, one product without price, an RFQ, supplier routing, `END`, and a new message after `END` through the Twilio Sandbox.

## Decisions still requiring product approval

1. **Stale-row reconciliation:** current sync upserts products, inventory, and pricing but does not delete rows removed from Google Sheets. A snapshot reconciliation mode would prevent stale offers, but deletion policy and rollback rules must be approved first.
2. **Suture family questionnaire:** the next search iteration should ask material, absorbability, size, needle, and pack configuration before showing SKU-level offers. Confirm the preferred clinical/business terminology before implementing it.
3. **Expanded database schema:** importing subcategory, manufacturer, regulatory class, search tags, inventory status, currency, and validity dates would improve filtering and governance but requires an Alembic migration and clear data ownership.
4. **Availability language:** choose whether blank stock means “source on request,” “availability to be confirmed,” or hides the offer. The code currently uses cautious sourcing language.
5. **Automated sync ownership:** approve either a manual GitHub Actions sync button or a scheduled job. A manual action is recommended for beta because it gives you a review gate without requiring Render's paid pre-deploy feature.
