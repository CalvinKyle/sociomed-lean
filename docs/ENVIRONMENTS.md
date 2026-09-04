# SocioMed Environments

This repo supports two safe environment patterns:

- Local machines: `.env.local` plus a local Google credentials file in `.secrets/`
- Production: environment variables only, including `GOOGLE_CREDS_JSON`

Real Twilio, Meta, Google, database, and application secrets must never be committed to git.

## 1. Shared Identity

Set these in every environment:

| Variable | Local value | Production value | Notes |
| --- | --- | --- | --- |
| `APP_ENV` | `development` | `production` | Production turns on stricter startup validation. |
| `PUBLIC_BASE_URL` | `http://localhost:8000` | Your public HTTPS Render URL | Use the Render URL first if the custom domain is not live yet. |
| `SUPPORT_EMAIL` | `sales@socio-med.com` | `sales@socio-med.com` | Buyer-facing contact. |
| `SALES_AGENT_PHONE` | `+254700123456` | Your live E.164 operations number | Buyer leads and RFQs are forwarded here. |
| `DEFAULT_CURRENCY` | `UGX` | `UGX` | Buyer phone prefixes still override this where supported. |
| `ENABLE_OPEN_DOCS` | `true` | `false` | Keep docs off in production. |
| `API_KEY` | `sociomed-local-api-key` | Strong random secret | Required for protected API and health endpoints. |
| `LOG_LEVEL` | `INFO` | `INFO` | Raise to `DEBUG` only while troubleshooting. |

## 2. Select the WhatsApp Provider and Processing Mode

| Variable | Sandbox value | Production value | Purpose |
| --- | --- | --- | --- |
| `WHATSAPP_PROVIDER` | `twilio` | `twilio` or `meta` | Selects the inbound and outbound provider. |
| `ASYNC_WHATSAPP_PROCESSING` | `false` | `true` when a Celery worker is deployed | Controls whether the Twilio webhook processes immediately or queues to Celery. |

With `ASYNC_WHATSAPP_PROCESSING=false`, the Twilio webhook awaits the existing WhatsApp handler in the Render web service and returns TwiML after processing. This is the recommended low-volume Sandbox configuration and does not require a paid Celery worker.

With `ASYNC_WHATSAPP_PROCESSING=true`, the webhook queues the same handler through Celery. Enable this only when the web service and Celery worker share the same Redis instance.

Redis is required in both modes for sessions, caching, duplicate-message protection, and per-sender locks.

## 3. Twilio WhatsApp Beta

These power `/api/webhook/twilio`, outbound WhatsApp messages, request validation, and delivery callbacks:

| Variable | Value to set |
| --- | --- |
| `TWILIO_ACCOUNT_SID` | Twilio Account SID beginning with `AC` |
| `TWILIO_AUTH_TOKEN` | Primary Twilio Auth Token; store only in `.env.local` or Render |
| `TWILIO_WHATSAPP_FROM` | Exact Sandbox or approved sender, including `whatsapp:` |
| `TWILIO_WEBHOOK_URL` | Exact public URL ending in `/api/webhook/twilio` |
| `TWILIO_STATUS_CALLBACK_URL` | Recommended public URL ending in `/api/webhook/twilio/status` |

The webhook URL configured in Twilio and `TWILIO_WEBHOOK_URL` must match exactly because Twilio signs the complete URL and all form parameters.

Follow [TWILIO_BETA.md](TWILIO_BETA.md) for the Console, Sandbox, Render, deployment, and smoke-test sequence. The deterministic routing and privacy contract is documented in [WHATSAPP_INTENT_FLOW.md](WHATSAPP_INTENT_FLOW.md).

## 4. Meta WhatsApp Cloud API

These power `/api/webhook` and Meta outbound notifications when `WHATSAPP_PROVIDER=meta`:

| Variable | Value to set |
| --- | --- |
| `VERIFY_TOKEN` | A private webhook verification value |
| `WHATSAPP_TOKEN` | Permanent Meta system-user token |
| `PHONE_NUMBER_ID` | Meta WhatsApp phone number ID |
| `WHATSAPP_APP_SECRET` | Meta app secret used for webhook signature validation |

The Meta webhook URL is `https://YOUR-HOST/api/webhook`.

## 5. Google Sheets Sync

Use one of these, not both:

- Local machines:
  - `GOOGLE_CREDS_FILE=.secrets/google-service-account.json`
  - Put the downloaded Google service account JSON file at `.secrets/google-service-account.json`
- Production:
  - Set `GOOGLE_CREDS_JSON` to the full service-account JSON as a single-line Render secret

Use `SHEET_NAME=sociomed_db` in both environments.

## 6. Data Layer

Use the same database and Redis instance for the web service and Celery worker:

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

Health checks serve two distinct purposes:

- `GET /api/health/liveness` is unauthenticated and returns only `{"status": "ok"}`.
- `GET /api/health` requires `X-API-Key` and reports database, Redis, and Google Sheets credential checks.

Exchange rates can be overridden without a deploy:

| Variable | Example |
| --- | --- |
| `EXCHANGE_RATES_JSON` | `{"KES":0.029,"RWF":0.36}` |
| `EXCHANGE_RATES_LAST_UPDATED` | Current source date in `YYYY-MM-DD` format |
| `MAX_EXCHANGE_RATE_AGE_DAYS` | `14` |

## 7. Render Services

For a Twilio Sandbox beta, only these services are required:

1. `sociomed-lean` web API
2. `sociomed-redis`
3. `sociomed-postgres`

Set `ASYNC_WHATSAPP_PROCESSING=false` on the web service. The Celery worker, Celery beat, and Flower services can remain suspended or undeployed during Sandbox testing.

For later asynchronous production processing, the blueprint still defines:

1. `sociomed-lean-celery-worker`
2. `sociomed-lean-celery-beat`
3. `sociomed-lean-flower`

Important production rules:

- Deploy the Celery worker before changing `ASYNC_WHATSAPP_PROCESSING` to `true`.
- The web service and Celery worker must share WhatsApp credentials, Postgres, Redis, and sales-routing values.
- The Celery beat service also needs outbound provider credentials if scheduled WhatsApp digests are enabled.
- `render.yaml` uses `sync: false` for secrets, so add real values in the Render Environment page.
- `autoDeploy` is disabled for the web service; deploy manually after changing code or environment variables.

## 8. Cross-Device Workflow

Use this pattern so your laptop, VS Code, Codex, and Render stay in sync without copying secrets through git:

1. Keep code and placeholder examples in git.
2. Keep local secrets in `.env.local` and `.secrets/`.
3. Keep production secrets in Render.
4. Keep authoritative secret values in a password manager or secret vault outside the repo.
5. Never commit `.env.local`, `.secrets/`, credential JSON, Auth Tokens, or API keys.
6. Rotate any credential immediately if it is exposed in git, logs, screenshots, or chat.

## 9. Fastest Worker-Free Twilio Beta Sequence

1. Deploy the Twilio integration branch to the existing Render web service.
2. Set `WHATSAPP_PROVIDER=twilio` and `ASYNC_WHATSAPP_PROCESSING=false`.
3. Add the real Twilio values to the Render web service.
4. Keep Redis and Postgres connected; suspend the Celery worker.
5. Run `alembic upgrade head`.
6. Load the catalog with `python3 sync_sheets_to_db.py`.
7. Join each tester to the Twilio WhatsApp Sandbox.
8. Point the Twilio Sandbox `When a message comes in` URL to `/api/webhook/twilio` using `POST`.
9. Verify `/api/health/liveness` and send `hello` from a joined WhatsApp tester.
10. Complete a product search and test RFQ to confirm the full flow.

## 10. Local Machine Bootstrap

1. Copy [.env.example](../.env.example) to `.env.local`.
2. Set `ASYNC_WHATSAPP_PROCESSING=false`.
3. Add real local Twilio values only to `.env.local`.
4. Create `.secrets/google-service-account.json`.
5. Start local Postgres and Redis.
6. Run `pip install -r requirements.txt`.
7. Run `alembic upgrade head`.
8. Run `python3 sync_sheets_to_db.py`.
9. Start the API with `uvicorn app.main:app --reload`.
10. Expose port 8000 with ngrok and use the exact HTTPS URL in `.env.local` and Twilio Sandbox settings.

A local Celery worker is not required while `ASYNC_WHATSAPP_PROCESSING=false`.
