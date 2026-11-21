# Pilot readiness changes

See ../CHANGES.md for the project change log.

- Step 1: owner-only supplier contact, corrected receipts and complete sales alerts.

- Step 2: API-key RFQ list and serialized, best-effort operations sheet snapshots (RFQs, lines, leads); shared lazy credentials, RAW values, separate destination guard.

- Step 3: shared quote/edit/review/approval/LPO workflow; 0014 migration; global rolling approval cap with immutable approval history and PostgreSQL transaction lock (single approvals count too). Editing invalidates quote/review/approval.
