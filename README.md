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
  Capture buyer interest from a landing page or sales form.
- `POST /api/rfqs`
  Submit quotation requests from a web form, sales ops tool, or onboarding workflow.
- `POST /api/webhook`
  Receives incoming WhatsApp messages from Meta.

## Quick Start

Recommended runtime: Python 3.11. The repo is now pinned with [runtime.txt](/Users/calvinainebyona/Desktop/sociomed-lean/runtime.txt).

```bash
cp .env.example .env.local
pip install -r requirements.txt
alembic upgrade head
python3 sync_sheets_to_db.py
uvicorn app.main:app --reload
```

Open [http://localhost:8000/docs](http://localhost:8000/docs) to test the procurement endpoints.

Production environment reference: [docs/ENVIRONMENTS.md](/Users/calvinainebyona/Desktop/sociomed-lean/docs/ENVIRONMENTS.md)
Data blueprint reference: [docs/DATA_BLUEPRINT.md](/Users/calvinainebyona/Desktop/sociomed-lean/docs/DATA_BLUEPRINT.md)

## Environment Sections

These are the concrete setup sections you need to address next:

1. Shared identity and routing
   Set `APP_ENV`, `PUBLIC_BASE_URL`, `SUPPORT_EMAIL`, `SALES_AGENT_PHONE`, `DEFAULT_CURRENCY`, `ENABLE_OPEN_DOCS`, and `LOG_LEVEL`.
2. Meta WhatsApp Cloud API
   Set `VERIFY_TOKEN`, `WHATSAPP_TOKEN`, `PHONE_NUMBER_ID`, and `WHATSAPP_APP_SECRET`.
3. Google Sheets sync
   Use `GOOGLE_CREDS_FILE=.secrets/google-service-account.json` locally or `GOOGLE_CREDS_JSON` in production, plus `SHEET_NAME=sociomed_db`.
4. Database and Redis
   Set `DATABASE_URL`, `REDIS_URL`, `SESSION_TTL=1800`, and `CACHE_TTL_SECONDS=300`.
5. Render deployment
   The web service and Celery worker must share the same WhatsApp, Postgres, Redis, and sales-routing variables.

Use [.env.example](/Users/calvinainebyona/Desktop/sociomed-lean/.env.example) for local machines and [.env.production.example](/Users/calvinainebyona/Desktop/sociomed-lean/.env.production.example) for production values.

## Architecture

WhatsApp Cloud API -> FastAPI -> PostgreSQL + Redis  
Google Sheets -> sync script -> PostgreSQL

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
- `rfq_requests`

## Launch Checklist

Before outreach, make sure these are done:

1. Load a high-confidence catalog into Sheets, then run `python3 sync_sheets_to_db.py`.
2. Set `SALES_AGENT_PHONE` so every buyer request gets routed to a human.
3. Deploy the API and verify `/api/health`, `/docs`, `/api/catalog/featured`, and `/api/catalog/search?q=gloves`.
4. Connect the Meta webhook to `/api/webhook` and confirm verification succeeds with `hub.verify_token`.
5. Create one simple outbound asset: a landing page, Notion page, or demo form pointed at `/api/leads` and `/api/rfqs`.
6. Use procurement-language messaging in outreach: faster supplier comparison, RFQ turnaround, stock visibility, and WhatsApp-native ordering.

## Async Processing

Webhook messages are offloaded to Celery for responsiveness.

- Run locally: `celery -A app.core.celery_app worker --loglevel=info`
- Monitor with Flower if needed

## Notes

- The app now initializes missing tables on startup via `init_db()`.
- Redis can be configured with either `REDIS_URL` or `REDIS_HOST` plus `REDIS_PORT`.
- Swagger docs can be disabled in production with `ENABLE_OPEN_DOCS=false`.
