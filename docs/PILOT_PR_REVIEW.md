# Pilot readiness review

Step 1 conflict: the requested SUPPLIER_DIRECT_NOTIFY=true legacy restoration would automatically send buyer identity to a supplier, violating hard rule 4. Supplier delivery is disabled unconditionally; the enabling flag is intentionally not implemented pending owner resolution. Sales alerts remain best effort and list stored lines, quantities, delivery and review flag.

Validation runtime: Python 3.12.14 (3.11.9 unavailable locally). Baseline 228 passed.
