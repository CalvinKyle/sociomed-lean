# Changes

## Pilot Readiness (steps 1–3)

- Render Blueprint: paid always-on web plan, paid Postgres and Key Value defaults, deploys from `main` and manual (`autoDeployTrigger: "off"`). Free Postgres expires after 30 days and free Key Value is not persistent.
- Catalogue API (`/api/catalog/*`) now requires the API key. Responses and the WhatsApp featured-offer copy no longer include `stock_qty`, `vendor_id` or `vendor_name`.
- Price gate: new `pricing.price_status` (migration `0013_price_status`, synced from the sheet). Buyers see a price only when it is `verified`, positive and not past `price_valid_until`; otherwise "Price on quotation". Existing prices start `unverified`.
- Catalogue lint (`app/core/catalogue_lint.py`, `scripts/lint_catalogue.py`), logged on every sync.
- Fix: dates in the cached dataset made `json.dumps` fail, silently disabling the Redis cache once a taxonomy version was active or any `price_valid_until` was set.

## Free-Tier Twilio Sandbox Deployment

- Run Alembic migrations with retries in the Docker start command, avoiding Render's paid pre-deploy feature.
- Reduce the Sandbox web service to one Gunicorn worker and remove paid worker services from the free-tier Blueprint.
- Add a public, non-secret `/api/health/twilio` readiness check for provider configuration, callback URL, database schema, and Redis.
- Reject incompatible Twilio Conversations payloads with an explicit error instead of silently returning success.
- Derive public and callback URLs from Render's automatic external URL when explicit values are not set.
- Keep Google Sheets credentials and sales routing optional for basic chat startup.

## Code Review Fixes

- Hardened WhatsApp webhook handling so non-text messages are acknowledged without crashing or corrupting the conversation state.
- Added API key authentication for protected API endpoints, keeping public catalog endpoints and the Meta webhook unauthenticated.
- Added RFQ status update support through the route, service, and data-access layers.
- Moved CI to `.github/workflows/ci.yml` with pinned Python and a `pytest` test run.
- Removed dead code and startup schema mutation in favor of Alembic-only migrations.
- Added an initial Alembic schema migration for existing models.
- Updated dependency pins and corrected the Redis client pin to remain compatible with Celery's Redis transport.
- Verified public domain references use `socio-med.com` and documented static exchange-rate fallback behavior.

## Round 2 Fixes

- Replaced clone-breaking absolute local links with repository-relative links.
- Added the proprietary SOCIOMED license and linked it from the README.
- Expanded the README with the current architecture, project structure, testing, contributing, and known-limitations guidance.
- Added a public process-only liveness endpoint while preserving the authenticated detailed health check.
- Pointed Docker and Render health probes at `/api/health/liveness` and documented the distinction between health endpoints.
- Added route coverage for the unauthenticated liveness response.

- Pilot step 1: disable supplier messaging; remove supplier contact from Redis options; team receipt copy; complete sales alerts with bounded chunks. Legacy flag conflict recorded in docs/PILOT_PR_REVIEW.md.

- Step 2: API-key RFQ list and serialized, best-effort operations sheet snapshots (RFQs, lines, leads); shared lazy credentials, RAW values, separate destination guard.

- Step 3: shared quote/edit/review/approval/LPO workflow; 0014 migration; global rolling approval cap with immutable approval history and PostgreSQL transaction lock (single approvals count too). Editing invalidates quote/review/approval.

- Step 4: mobile server-rendered /ops console with fail-closed Basic authentication, escaped content, same-origin and per-render cookie/form CSRF protection, using shared quote services.

- Step 5: structured natural/pipe item intake, per-item quantities, protected compound names, saved contact reuse, one-at-a-time missing fields and explicit confirmation; 20-item cap and verified tier resolution.

- Step 6: conservative buyer UoM glossary; null brand and lead-time wording cleaned in offers; raw unit codes removed from buyer menus and structured RFQ items.
