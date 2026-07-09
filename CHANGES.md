# Changes

## Code Review Fixes

- Hardened WhatsApp webhook handling so non-text messages are acknowledged without crashing or corrupting the conversation state.
- Added API key authentication for protected API endpoints, keeping public catalog endpoints and the Meta webhook unauthenticated.
- Added RFQ status update support through the route, service, and data-access layers.
- Moved CI to `.github/workflows/ci.yml` with pinned Python and a `pytest` test run.
- Removed dead code and startup schema mutation in favor of Alembic-only migrations.
- Added an initial Alembic schema migration for existing models.
- Updated dependency pins and corrected the Redis client pin to remain compatible with Celery's Redis transport.
- Verified public domain references use `sociomed.co` and documented static exchange-rate fallback behavior.
