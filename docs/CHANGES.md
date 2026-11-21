# Pilot readiness changes

See ../CHANGES.md for the project change log.

- Step 1: owner-only supplier contact, corrected receipts and complete sales alerts.

- Step 2: API-key RFQ list and serialized, best-effort operations sheet snapshots (RFQs, lines, leads); shared lazy credentials, RAW values, separate destination guard.

- Step 3: shared quote/edit/review/approval/LPO workflow; 0014 migration; global rolling approval cap with immutable approval history and PostgreSQL transaction lock (single approvals count too). Editing invalidates quote/review/approval.

- Step 4: mobile server-rendered /ops console with fail-closed Basic authentication, escaped content, same-origin and per-render cookie/form CSRF protection, using shared quote services.

- Step 5: structured natural/pipe item intake, per-item quantities, protected compound names, saved contact reuse, one-at-a-time missing fields and explicit confirmation; 20-item cap and verified tier resolution.

- Step 6: conservative buyer UoM glossary; null brand and lead-time wording cleaned in offers; raw unit codes removed from buyer menus and structured RFQ items.
