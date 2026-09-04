# SocioMed Lean

WhatsApp-native procurement infrastructure for medical supplies in East Africa.

Procurement teams can search products, compare supplier offers, and request quotations from WhatsApp or a lightweight landing page. Suppliers can receive matched RFQs in near real time.

## What To Ship This Week

If your goal is to get this in front of procurement teams and suppliers within the next few days, focus on these surfaces first:

1. `app/services/whatsapp_service.py`
   This is the real buyer journey. Buyers need to search, compare, request a quotation, and talk to sales without hitting placeholder states.
2. `app/api/routes.py`
   These routes are the fastest bridge to market. You can connect them to a simple landing page, Typeform, Retool, or a no-code frontend immediately.
3. `app/services/catalog.py`
   This powers a public procurement-facing catalog preview without building a full frontend first.
4. `app/services/procurement.py` and `app/models/db.py`
   These capture leads and RFQs so you have an actual pipeline instead of ephemeral chat messages.
5. `Dockerfile`, `app/core/config.py`, and `app/core/logging_config.py`
   These remove avoidable launch blockers in deploy and operations.

## Go-To-Market Endpoints

Once deployed, these are the endpoints worth handing to your first design partners:

- `GET /api/catalog/featured`
  Use this on a simple homepage to show live supplier-backed offers.
- `GET /api/catalog/search?q=surgical gloves`
  Use this for a procurement search box.
- `POST /api/leads`
  Capture buyer interest from a landing page or sales form. Requires `X-API-Key`.
- `POST /api/rfqs`
  Submit quotation requests from a web form, sales ops tool, or onboarding workflow. Requires `X-API-Key`.
- `POST /api/webhook/twilio`
  Receives signed incoming WhatsApp messages from the Twilio Sandbox or an approved Twilio sender.
- `POST /api/webhook/twilio/status`
  Receives signed Twilio delivery status callbacks.
- `POST /api/webhook`
  Retains support for incoming WhatsApp messages from Meta Cloud API.

## Quick Start

Recommended runtime: Python 3.11. The repo is now pinned with [runtime.txt](runtime.txt).

```bash
cp .env.example .env.local
pip install -r requirements.txt
alembic upgrade head
python3 sync_sheets_to_db.py
uvicorn app.main:app --reload
```

Open [http://localhost:8000/docs](http://localhost:8000/docs) to test the procurement endpoints.

Twilio beta guide: [docs/TWILIO_BETA.md](docs/TWILIO_BETA.md)
Production environment reference: [docs/ENVIRONMENTS.md](docs/ENVIRONMENTS.md)
Data blueprint reference: [docs/DATA_BLUEPRINT.md](docs/DATA_BLUEPRINT.md)
Intent-first WhatsApp flow: [docs/WHATSAPP_INTENT_FLOW.md](docs/WHATSAPP_INTENT_FLOW.md)

## Environment Sections

These are the concrete setup sections you need to address next:

1. Shared identity and routing
   Set `APP_ENV`, `PUBLIC_BASE_URL`, `SUPPORT_EMAIL`, `SALES_AGENT_PHONE`, `DEFAULT_CURRENCY`, `ENABLE_OPEN_DOCS`, `API_KEY`, and `LOG_LEVEL`.
2. WhatsApp provider and processing
   Set `WHATSAPP_PROVIDER=twilio` and `ASYNC_WHATSAPP_PROCESSING=false` for worker-free Sandbox testing. Set the processing flag to `true` only when a Celery worker is deployed.
3. Twilio WhatsApp
   Set `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `TWILIO_WHATSAPP_FROM`, `TWILIO_WEBHOOK_URL`, and optionally `TWILIO_STATUS_CALLBACK_URL`.
4. Meta WhatsApp Cloud API
   When using Meta, set `VERIFY_TOKEN`, `WHATSAPP_TOKEN`, `PHONE_NUMBER_ID`, and `WHATSAPP_APP_SECRET`.
5. Google Sheets sync
   Use `GOOGLE_CREDS_FILE=.secrets/google-service-account.json` locally or `GOOGLE_CREDS_JSON` in production, plus `SHEET_NAME=sociomed_db`.
6. Database and Redis
   Set `DATABASE_URL`, `REDIS_URL`, `SESSION_TTL=3600`, `SESSION_VERSION=2`, `SMALL_RFQ_MAX_ITEMS=5`, and `CACHE_TTL_SECONDS=300`.
7. Render deployment
   Sandbox mode needs the web service, Redis, and Postgres. Production async mode also needs a Celery worker sharing the same provider credentials and Redis instance.

Use [.env.example](.env.example) for local machines and [.env.production.example](.env.production.example) for production values. The examples contain placeholders only; real credentials belong in `.env.local` or the Render Environment page.

## Architecture

```text
Twilio / Meta WhatsApp ──▶ FastAPI (routes) ──▶ services ──▶ data_access ──▶ PostgreSQL
                                  │                                   ▲
                                  ├── synchronous Sandbox             │
                                  ▼                                   │
                         Celery (optional async)                 Redis (state)
                                  │
                          Google Sheets ──▶ sync_sheets_to_db.py ──▶ PostgreSQL
```

## Project Structure

- `app/api/` — FastAPI routes and HTTP request handling.
- `app/services/` — Catalog, procurement, WhatsApp, and asynchronous business workflows.
- `app/data_access/` — Database queries and persistence operations.
- `app/models/` — SQLAlchemy database models and model formatting helpers.
- `app/schemas/` — Pydantic request and response schemas.
- `app/integrations/` — External service adapters, including Google Sheets.
- `app/core/` — Configuration, authentication, caching, currency, logging, and shared infrastructure.
- `migrations/` — Alembic database migrations.
- `tests/` — Automated pytest coverage for routes, services, and data behavior.
- `docs/` — Environment, Twilio beta, and data-blueprint documentation.

## Product Model

SocioMed is intentionally `RFQ-first`.

- Persist buyer leads and RFQs.
- Do not force a cart-and-checkout order flow yet.
- Use WhatsApp to shortlist offers, capture quantity, and route to supplier or sales follow-up.

## Local Data Model

Primary catalog tables:

- `products`
- `vendors`
- `inventory`
- `pricing`
- `aliases`

Commercial pipeline tables:

- `buyer_leads`
- `buyer_profiles`
- `rfq_requests`
- `rfq_line_items`

## Launch Checklist

Before outreach, make sure these are done:

1. Load a high-confidence catalog into Sheets, then run `python3 sync_sheets_to_db.py`.
2. Set `SALES_AGENT_PHONE` so every buyer request gets routed to a human.
3. Deploy the API and verify authenticated `/api/health`, `/docs`, public `/api/catalog/featured`, and public `/api/catalog/search?q=gloves`.
4. For Twilio beta, set `ASYNC_WHATSAPP_PROCESSING=false`, follow [docs/TWILIO_BETA.md](docs/TWILIO_BETA.md), join each tester to the Sandbox, and point the Sandbox webhook to `/api/webhook/twilio`.
5. For Meta, connect the webhook to `/api/webhook` and confirm verification succeeds with `hub.verify_token`.
6. Create one simple outbound asset: a landing page, Notion page, or demo form pointed at authenticated `/api/leads` and `/api/rfqs`.
7. Use procurement-language messaging in outreach: faster supplier comparison, RFQ turnaround, stock visibility, and WhatsApp-native ordering.

## WhatsApp Processing Modes

For low-volume Twilio Sandbox testing:

```text
ASYNC_WHATSAPP_PROCESSING=false
```

The web service runs the existing WhatsApp handler directly. Redis still provides sessions, caching, duplicate protection, and sender locks. A Celery worker is not required.

For production asynchronous processing:

```text
ASYNC_WHATSAPP_PROCESSING=true
```

Deploy a Celery worker connected to the same Redis instance:

```bash
celery -A app.core.celery_app worker --loglevel=info
```

## Testing

```bash
pytest tests/ -v --cov=app --cov-report=term-missing
```

CI runs the test suite automatically via `.github/workflows/ci.yml` on every push and pull request.

## Contributing

Run the test suite locally before opening a pull request. All pull requests are reviewed before merge.

## Known Limitations

- There is no admin or vendor self-service UI yet; catalog changes go through Google Sheets and `sync_sheets_to_db.py`.
- Exchange rates remain static unless `EXCHANGE_RATES_JSON` is set.

## Notes

- Schema changes are handled only by Alembic migrations; run `alembic upgrade head` before starting or syncing.
- Redis can be configured with either `REDIS_URL` or `REDIS_HOST` plus `REDIS_PORT`.
- Swagger docs can be disabled in production with `ENABLE_OPEN_DOCS=false`.
- Keep `TWILIO_AUTH_TOKEN`, Meta tokens, Google credentials, database passwords, and API keys out of git.

## License

This project is proprietary and confidential; see [LICENSE](LICENSE).
