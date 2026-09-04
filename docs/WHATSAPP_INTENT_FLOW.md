# WhatsApp Intent-First Buyer Flow

This document defines the launch behavior for the SocioMed medical-supplies sales desk. It applies to both Twilio synchronous Sandbox processing and the optional Celery path because both invoke the same WhatsApp service.

## Scope

- Medical supplies and medical equipment only.
- Medicines and pharmaceuticals are not handled.
- Product, RFQ, pricing, and PFI generation rules remain in their existing services.
- Redis remains required for sessions, cache, duplicate-message claims, and sender locks.
- Low-volume Twilio Sandbox deployments should use `ASYNC_WHATSAPP_PROCESSING=false`.

## Entry Routing Priority

The first buyer message is classified deterministically in this order:

1. Global navigation
2. Medicines restriction
3. Sales or human handoff
4. Formal purchase / RFQ
5. Multi-item list
6. Product plus quantity
7. Product
8. Catalogue category
9. Greeting
10. Unknown input

A greeting displays the menu. A product name starts search immediately; buyers do not need to enter the menu first.

## Global Commands

| Command | Action |
| --- | --- |
| `1` or `SEARCH` | Start product search |
| `2` or `CATEGORIES` | Browse the live Sheets-backed taxonomy |
| `3` or `QUOTE` | Start a formal RFQ |
| `4` or `SALES` | Open a sales handoff |
| `0`, `MENU`, or `BACK` | Return to the main menu |

Word commands work from every conversation state. Numeric responses remain state-aware after entry so product and offer selections continue to work.

## Buyer Privacy

Buyer-facing catalogue responses may show:

- Product and brand
- Unit of measure
- Indicative price or price range
- Availability band
- Indicative lead time

They must not show supplier names, supplier phone numbers, vendor identifiers, or exact stock quantities. Those fields remain in internal session and RFQ data for fulfillment and sales operations.

## Procurement Intent and Notifications

Browsing and market-intelligence searches do not notify sales. Sales notifications are appropriate for:

- Formal purchase or RFQ submission
- Explicit sales handoff
- Sourcing request for an unavailable item
- Multi-item request
- Equipment technical review

The policy lives in `app/services/procurement_policy.py`.

`SMALL_RFQ_MAX_ITEMS=5` defines the small-list threshold. Larger or complex lists remain manual-review cases. Equipment RFQs use `equipment_technical_review` as the manual-review reason. PFI generation remains a separate authenticated action and is not triggered automatically by chat.

## Returning Buyers

Completed RFQs update a PostgreSQL buyer profile keyed by phone number. The profile stores contact name, organization, delivery location, country when supplied, and preferred currency. A returning buyer can enter:

```text
Surgical gloves | 25
```

after choosing `QUOTE` to reuse the saved organization and delivery location. The full RFQ format remains available when details changed.

## Catalogue Sheet Additions

The following columns are optional and sync safely when absent:

- Products: `product_family_id`
- Products: `equipment_review_required`
- Pricing: `price_valid_until`

Run `alembic upgrade head` before the first sync after deploying this branch.

## Render Sandbox Values

Set these on the Render web service:

```text
WHATSAPP_PROVIDER=twilio
ASYNC_WHATSAPP_PROCESSING=false
SESSION_TTL=3600
SESSION_VERSION=2
SMALL_RFQ_MAX_ITEMS=5
```

Keep the real Twilio credentials, PostgreSQL URL, Redis URL, Google credentials, API key, and sales phone in Render environment variables. Never commit them.

## Smoke Test

1. Run `alembic upgrade head`.
2. Run `python3 sync_sheets_to_db.py`.
3. Confirm `/api/health/liveness` returns HTTP 200.
4. Send `hello`; verify the four-option menu.
5. Send `10 boxes of surgical gloves`; verify direct search and quantity acknowledgement.
6. Send `CATEGORIES`; verify live categories.
7. Send a medicine name; verify the medical-supplies-only response.
8. Send `QUOTE`; submit one RFQ and verify PostgreSQL persistence and the sales notification.
9. Resend the same Twilio Message SID; verify duplicate protection skips it.
10. Keep the Celery worker suspended while `ASYNC_WHATSAPP_PROCESSING=false`.
