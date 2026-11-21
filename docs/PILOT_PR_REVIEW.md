# Pilot readiness review

Step 1 conflict: the requested SUPPLIER_DIRECT_NOTIFY=true legacy restoration would automatically send buyer identity to a supplier, violating hard rule 4. Supplier delivery is disabled unconditionally; the enabling flag is intentionally not implemented pending owner resolution. Sales alerts remain best effort and list stored lines, quantities, delivery and review flag.

Validation runtime: Python 3.12.14 (3.11.9 unavailable locally). Baseline 228 passed.

UoM confirmation needed: PC1, BP1, BP12, BPR1, BP100, BTL1, KIT, JC1, BP10, BTS50, BPR100. Conservative pack labels intentionally do not promise a pack size; confirm all mappings in app/content/uom_labels.json. Unknown codes become unit.
