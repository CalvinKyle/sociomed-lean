# Code Review TODO

## Critical

- DONE: Fix the WhatsApp handler so non-text messages do not crash the flow and receive a helpful reply.
- DONE: Move CI to `.github/workflows/ci.yml`, pin Python, and run `pytest`.

## High

- DONE: Add API key authentication to protected endpoints while keeping catalog browse/search/featured and the Meta WhatsApp webhook public.
- DONE: Add route and layered service support for updating RFQ status.

## Medium

- DONE: Remove dead code, including the unused Redis session manager and exchange-rate updater.
- DONE: Standardize schema changes on Alembic migrations and remove runtime schema mutation.
- DONE: Update stale dependencies while keeping the dependency graph installable.
- DONE: Verify domain references use `socio-med.com`.
- DONE: Clarify static exchange-rate fallback behavior.
