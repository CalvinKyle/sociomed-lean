# SocioMed Environments

This repo now supports two safe environment patterns:

- Local machines: `.env.local` plus a local Google credentials file in `.secrets/`
- Production: environment variables only, including `GOOGLE_CREDS_JSON`

## 1. Shared Identity

Set these in every environment:

| Variable | Local value | Production value | Notes |
| --- | --- | --- | --- |
| `APP_ENV` | `development` | `production` | Production turns on stricter startup validation. |
| `PUBLIC_BASE_URL` | `http://localhost:8000` | `https://api.socio-med.com` | Use your Render URL first if the custom domain is not live yet. |
| `SUPPORT_EMAIL` | `sales@socio-med.com` | `sales@socio-med.com` | Buyer-facing contact. |
| `SALES_AGENT_PHONE` | `+254700123456` | Your live E.164 ops number | This is where buyer leads and RFQs are forwarded. |
| `DEFAULT_CURRENCY` | `UGX` | `UGX` | Buyer phone prefixes still override this where supported. |
| `ENABLE_OPEN_DOCS` | `true` | `false` | Keep docs off in production. |
| `API_KEY` | `sociomed-local-api-key` | Strong random secret | Required for `/`, `/api/health`, leads, RFQs, and RFQ status updates. Public catalog and Meta webhook endpoints do not require it. |
| `LOG_LEVEL` | `INFO` | `INFO` | Raise to `DEBUG` only when actively troubleshooting. |

## 2. Meta WhatsApp Cloud API

These power `/api/webhook` and all outbound WhatsApp notifications:

| Variable | Value to set |
| --- | --- |
| `VERIFY_TOKEN` | `sociomed-local-webhook` locally and `sociomed-prod-webhook` in production |
| `WHATSAPP_TOKEN` | Paste the permanent Meta system-user token |
| `PHONE_NUMBER_ID` | Paste the Meta WhatsApp phone number ID |
| `WHATSAPP_APP_SECRET` | Paste the Meta app secret used for webhook signature validation |

The webhook URL should be `https://api.socio-med.com/api/webhook` once production is live.

## 3. Google Sheets Sync

Use one of these, not both:

- Local machines:
  - `GOOGLE_CREDS_FILE=.secrets/google-service-account.json`
  - Put the downloaded Google service account JSON file at `.secrets/google-service-account.json`
- Production:
  - `GOOGLE_CREDS_JSON=` and paste the full service-account JSON as a single-line value

Use:

- `SHEET_NAME=sociomed_db`

That keeps the sync script consistent on your laptop, VS Code, Codex, and Render shell sessions.

## 4. Data Layer

Use the same database and Redis instance for the web service and the Celery worker:

| Variable | Local value | Production value |
| --- | --- | --- |
| `DATABASE_URL` | `postgresql://sociomed:sociomed_dev_password@localhost:5432/sociomed_local` | Render Postgres internal connection string |
| `REDIS_URL` | `redis://localhost:6379/0` | Render Redis internal connection string |
| `SESSION_TTL` | `1800` | `1800` |
| `SESSION_VERSION` | `1` | Increment only when old Redis sessions should be flushed |
| `CACHE_TTL_SECONDS` | `300` | `300` |
| `DB_POOL_SIZE` | `5` | Hosted Postgres pool size |
| `DB_MAX_OVERFLOW` | `10` | Temporary extra DB connections |
| `DB_POOL_RECYCLE_SECONDS` | `300` | Recycle stale DB connections |

The app now preserves Redis credentials from `REDIS_URL`, which matters for managed Redis services.

Exchange rates can be overridden without a deploy:

| Variable | Example |
| --- | --- |
| `EXCHANGE_RATES_JSON` | `{"KES":0.029,"RWF":0.36}` |
| `EXCHANGE_RATES_LAST_UPDATED` | `2026-04-30` |
| `MAX_EXCHANGE_RATE_AGE_DAYS` | `14` |

If `EXCHANGE_RATES_JSON` is not set, the app uses conservative static fallback rates from code and treats freshness based on `EXCHANGE_RATES_LAST_UPDATED`.

## 5. Render Services

You need three services:

1. `sociomed-lean` web API
2. `sociomed-lean-celery-worker` Celery worker
3. `sociomed-lean-flower` optional monitoring dashboard

Important production rule:

- The worker must receive the same WhatsApp, Postgres, Redis, and sales-routing variables as the web service.

That mismatch was a deploy blocker before this update; it is now reflected in [render.yaml](/Users/calvinainebyona/Desktop/sociomed-lean/render.yaml).

## 6. Cross-Device Workflow

Use this pattern so your laptop, VS Code, and Codex stay in sync without copying secrets through git:

1. Keep code in git.
2. Keep local secrets in `.env.local` and `.secrets/`.
3. Keep production secrets in Render.
4. Keep the authoritative secret values in one shared vault outside the repo.
5. Never commit `.env*`, `.secrets/`, or `credentials.json`.

## 7. Fastest Production Sequence

1. Fill in [.env.production.example](/Users/calvinainebyona/Desktop/sociomed-lean/.env.production.example) with the real production values.
2. Mirror those values into Render for both the web service and the worker.
3. Deploy the API and worker.
4. Run `alembic upgrade head`.
5. Run `python3 sync_sheets_to_db.py --dry-run` against production once the Google credentials are in place.
6. Run `python3 sync_sheets_to_db.py` after the dry-run row counts look correct.
7. Verify `/api/health` with `X-API-Key`, public `/api/catalog/featured`, public `/api/catalog/search?q=gloves`, authenticated `POST /api/leads`, authenticated `POST /api/rfqs`, and the Meta webhook verification flow.
8. Point Meta at `https://api.socio-med.com/api/webhook`.

## 8. Local Machine Bootstrap

1. Copy [.env.example](/Users/calvinainebyona/Desktop/sociomed-lean/.env.example) to `.env.local`.
2. Create `.secrets/google-service-account.json`.
3. Start local Postgres and Redis.
4. Run `pip install -r requirements.txt`.
5. Run `alembic upgrade head`.
6. Run `python3 sync_sheets_to_db.py`.
7. Start the API with `uvicorn app.main:app --reload`.
8. Start the worker with `celery -A app.core.celery_app worker --loglevel=info`.
