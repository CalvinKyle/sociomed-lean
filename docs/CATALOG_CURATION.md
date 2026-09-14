# Catalog curation

The source of truth remains Google Sheets. Deploy migrations through `0012_pricing_currency`, then run the existing sync (CLI, authenticated manual endpoint, or scheduled run). A dry run stages and rolls back changes, including version history.

| Decision | Source fields | Runtime behavior |
| --- | --- | --- |
| Product visibility | `products.active` | False hides products from search and browse. Blank or missing means true. |
| Product identity | `products.product_id`, `name`, `product_family_id` | Keep IDs stable. Family members appear under one parent, then variants. |
| Parent display name | Approved `product_families.name` in the active taxonomy | Falls back to known family labels or a readable family ID. `parent_products.parent_name` and `family_dict.family_name` are not imported. |
| Family placement and order | Optional `parent_products`: `product_family_id`, `category_id`, `department`, `page`, `position` | Stored as `product_family_curation`; curated families sort first by page and position. |
| Browse navigation | Optional `browse_menu`: `node_id`, `parent_node_id`, `label`, `node_type`, `page`, `position`, `category_id`, `department`, `next_action` | CATEGORY labels lead to their SPECIALTY children. Order follows page/position; four specialties per message. Filters match category ID and department against curation, or product category/specialty when no curation exists. |
| Variant specifications | Approved `product_attributes` in the active taxonomy | Size, gauge, needle profile, lumen, material and length distinguish variants. Missing attributes fall back to name/SKU. |
| Supplier SKU and pack | `inventory.sku`, `brand`, `uom`, `product_id`, `vendor_id` | Supplier offers use inventory fields. Product-level SKU/UOM fields do not override inventory. |
| Price | `pricing.pricing_id`, `inventory_id`, `min_qty`, `max_qty`, `unit_price`, `currency`, `price_valid_until` | Native currency defaults to UGX. Conversion uses source → UGX → buyer currency. Ranges are separated by displayed currency and UOM. |
| Related products | `products.related_ids` | Use verified product IDs; source review notes do not establish compatibility. |

`parent_products` and `browse_menu` are optional. An empty database table preserves the original browse behavior. Sync upserts these overlays: removing a tab does not delete previously imported rows. There is no import of `browse_memberships`, `offer_lines`, `family_offers`, `featured_products`, or `product_attributes_review`.

## Review order

1. Check category/specialty labels and parent-node links in `browse_menu`.
2. Correct each family's category ID, department, page and position in `parent_products`.
3. Review product name, family assignment and active state. Avoid merging distinct sizes or packs merely because names match.
4. Check inventory SKU, supplier, brand and UOM. Keep pack quantities explicit.
5. Check every pricing tier's ID, inventory link, currency, minimum, maximum and unit price. Missing IDs or invalid ranges are skipped and logged.
6. Approve variant attributes and family names through the normalized taxonomy workflow; review-only tabs do not activate them.
7. Dry-run the sync, inspect skipped rows, then run a real sync and test category navigation, exact SKU search, variants and offers.

Review workbooks are correction ledgers, not direct replacements for the source tabs. Copy approved corrections by their stable row IDs into the named source tab; use the recorded source row number to locate rows that have no ID yet. Preserve original values until corrections are approved.

Supported exchange rates are defined in `EXCHANGE_RATES`; unsupported source currencies fail explicitly rather than silently mispricing an offer. UGX-only legacy fixtures retain their conversion behavior.
