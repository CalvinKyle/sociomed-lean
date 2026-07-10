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

## Round 2

- DONE: Replace absolute local paths in README and environment documentation with relative links.
- DONE: Add a proprietary LICENSE file using the confirmed SOCIOMED legal entity name and link it from the README.
- DONE: Upgrade the README with architecture, project structure, testing, contributing, and known limitations sections.
- DONE: Split the public process liveness check from the authenticated detailed health check and update infrastructure probes.
- DONE: Document and test the public liveness endpoint.
