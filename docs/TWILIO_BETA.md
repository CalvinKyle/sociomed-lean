# Twilio WhatsApp Beta Setup

The Twilio integration is configured through environment variables. Real credentials must be stored in Twilio and Render, never committed to git.

For low-volume Sandbox testing, set `ASYNC_WHATSAPP_PROCESSING=false`. The Render web service will process each inbound message directly and no paid Celery background worker is required. Redis remains required for conversation sessions, caching, sender locks, and duplicate-message protection.

The free-tier deployment runs `alembic upgrade head` from `scripts/start_web.sh` before Gunicorn starts. This replaces Render's paid pre-deploy command for the beta environment.

## What Was Added

- `WHATSAPP_PROVIDER=twilio` switches outbound WhatsApp delivery from Meta Cloud API to Twilio.
- `POST /api/webhook/twilio` accepts Twilio's form-encoded inbound WhatsApp webhooks.
- `X-Twilio-Signature` is validated with the Twilio Auth Token before processing.
- `ASYNC_WHATSAPP_PROCESSING=false` runs the existing WhatsApp handler inside the web request.
- `ASYNC_WHATSAPP_PROCESSING=true` preserves the Celery queue and worker architecture for production.
- `POST /api/webhook/twilio/status` records Twilio delivery status callbacks in the audit log.
- Incoming Twilio payloads are translated into the existing SocioMED conversation flow, so catalog, RFQ, supplier notification, and sales handoff behavior stays unchanged.

Both modes use the same message-processing service and Redis session lock. See [WHATSAPP_INTENT_FLOW.md](WHATSAPP_INTENT_FLOW.md) for the buyer-routing and privacy contract. If inline processing fails, the message's duplicate-protection claim is released and the webhook returns an error so Twilio can retry.

## 1. Get the Twilio Values

Open the [Twilio Console](https://console.twilio.com/) and collect these values:

| Environment variable | Where to find it | Example format |
| --- | --- | --- |
| `TWILIO_ACCOUNT_SID` | Account Dashboard / Account Info | `AC...` |
| `TWILIO_AUTH_TOKEN` | Account Dashboard / Account Info, reveal the primary Auth Token | Secret value; do not commit it |
| `TWILIO_WHATSAPP_FROM` | Messaging > Try it out > Send a WhatsApp message > Sandbox sender | `whatsapp:+14155238886` or the sender Twilio assigns |
| `TWILIO_WEBHOOK_URL` | Your deployed SocioMED URL plus the inbound path | `https://YOUR-SERVICE.onrender.com/api/webhook/twilio` |
| `TWILIO_STATUS_CALLBACK_URL` | Your deployed SocioMED URL plus the status path | `https://YOUR-SERVICE.onrender.com/api/webhook/twilio/status` |

Use the exact Sandbox sender shown in your Twilio Console. Do not assume the example number is the sender assigned to your account.

## 2. Join the WhatsApp Sandbox

1. In Twilio Console, open **Messaging > Try it out > Send a WhatsApp message**.
2. Follow the displayed instructions to send the account's `join ...` code from each beta tester's WhatsApp number to the Twilio Sandbox sender.
3. Confirm Twilio shows that the tester joined the Sandbox.

Every tester must join the Sandbox before the Sandbox can exchange WhatsApp messages with that phone number.

## 3. Configure the Render Web Service

In the Render dashboard, open the existing `sociomed-lean` web service and go to **Environment**.

Set:

```text
WHATSAPP_PROVIDER=twilio
ASYNC_WHATSAPP_PROCESSING=false
RUN_DB_MIGRATIONS=true
WEB_CONCURRENCY=1
SESSION_TTL=3600
SESSION_VERSION=2
SMALL_RFQ_MAX_ITEMS=5
TWILIO_ACCOUNT_SID=AC...
TWILIO_AUTH_TOKEN=your-real-primary-auth-token
TWILIO_WHATSAPP_FROM=whatsapp:+YOUR_TWILIO_SANDBOX_NUMBER
TWILIO_WEBHOOK_URL=https://YOUR-SERVICE.onrender.com/api/webhook/twilio
TWILIO_STATUS_CALLBACK_URL=https://YOUR-SERVICE.onrender.com/api/webhook/twilio/status
PUBLIC_BASE_URL=https://YOUR-SERVICE.onrender.com
```

`PUBLIC_BASE_URL` and the two Twilio callback URLs can be derived from Render's automatic `RENDER_EXTERNAL_URL`, but keeping the explicit `TWILIO_WEBHOOK_URL` is recommended because it makes signature troubleshooting unambiguous.

Postgres and Redis are runtime requirements. The Blueprint generates an `API_KEY`, but a missing key only disables protected HTTP endpoints and does not block WhatsApp startup. Google credentials are only needed when running the Sheets sync, and `SALES_AGENT_PHONE` is only needed to test the human handoff and sales notification path.

You can suspend or omit the Celery worker during Sandbox testing. Do not remove Redis: the synchronous path still uses it for sessions, caching, duplicate-message claims, and sender locks.

The free-tier `render.yaml` intentionally defines only the web service, Postgres, and Key Value. Add worker services later when moving back to asynchronous processing.

## 4. Configure the Twilio Sandbox Webhook

1. Return to **Messaging > Try it out > Send a WhatsApp message**.
2. Open **Sandbox settings**.
3. In **When a message comes in**, enter the exact value used for `TWILIO_WEBHOOK_URL`.
4. Select `POST`.
5. Save the Sandbox configuration.

The URL in Twilio and `TWILIO_WEBHOOK_URL` must match exactly, including `https`, hostname, path, query string, and trailing slash behavior. Twilio includes the complete URL when calculating `X-Twilio-Signature`.

The application sends `TWILIO_STATUS_CALLBACK_URL` with every outbound message, so no separate Sandbox status URL is required.

## 5. Deploy and Migrate Without a Celery Worker

The Blueprint tracks `codex/twilio-whatsapp-beta` and deploys commits automatically. If the existing service is not managed by the Blueprint, set that branch and trigger a manual deploy in the dashboard.

1. Set `ASYNC_WHATSAPP_PROCESSING=false` and `RUN_DB_MIGRATIONS=true` on the web service.
2. Deploy `sociomed-lean`; the container retries `alembic upgrade head` before starting Gunicorn.
3. Leave the Celery worker, beat, and Flower undeployed.
4. Wait for the deploy log to show the migration reaching the current head and Gunicorn starting.
5. Open `GET https://YOUR-SERVICE.onrender.com/api/health/twilio` until it returns HTTP 200 with every check set to `true`.

Render free web services sleep after inactivity. Always open the Twilio readiness URL and wait for it to return before sending the first Sandbox message of a test session.

## 6. Beta Smoke Test

From a phone that joined the Sandbox, after `/api/health/twilio` reports `ready`:

1. Send `hello` to the Twilio Sandbox WhatsApp number.
2. Confirm the SocioMED main menu arrives.
3. Send `10 boxes of surgical gloves` and confirm search starts without a menu detour.
4. Send `CATEGORIES` and confirm the live taxonomy appears.
5. Reply `QUOTE` and submit a sample RFQ.
6. Confirm the RFQ and buyer profile are saved and the sales notification is attempted.
7. Check Render logs for `twilio_whatsapp_delivery_status` audit events.

Twilio/WhatsApp free-form replies are intended for the active customer-service conversation window. For proactive messages outside that window, configure approved WhatsApp Content Templates before production use.

## Switching Back to Celery for Production

When traffic or processing time grows:

1. Deploy and configure `sociomed-lean-celery-worker` with the same Twilio, Postgres, and Redis values as the web service.
2. Confirm the worker is healthy.
3. Set `ASYNC_WHATSAPP_PROCESSING=true` on the web service.
4. Redeploy the web service.
5. Send a test message and confirm the web service queues it and the worker processes it.

Do not set the flag to `true` unless a working Celery worker is connected to the same Redis instance.

## Local Testing With ngrok

For local Sandbox testing:

```bash
uvicorn app.main:app --reload
ngrok http 8000
```

Set `ASYNC_WHATSAPP_PROCESSING=false` in `.env.local`; a local Celery worker is not needed. Replace the ngrok placeholder with the current HTTPS forwarding hostname and use that exact URL in Twilio Sandbox settings. Restart the API after changing `.env.local`.

## Troubleshooting

- `403 invalid Twilio webhook signature`: confirm the primary Auth Token is correct and the configured webhook URL exactly matches Twilio's URL.
- `/api/health/twilio` returns `503`: inspect the false check. It distinguishes provider, inline mode, credentials, callback URL, database, schema, and Redis failures without displaying secrets.
- Deploy fails before Gunicorn starts: inspect the Alembic error. The start script retries database connectivity for up to one minute and refuses to run incompatible application code against an old schema.
- Webhook returns `400 unsupported Twilio payload`: the callback is not a Programmable Messaging webhook. Confirm the Sandbox's **When a message comes in** field is being used, not a Conversations Service callback.
- Webhook returns `500`: inspect the web-service log. The message claim is released so a Twilio retry can process it again.
- Webhook returns `200` but no WhatsApp reply arrives: confirm `ASYNC_WHATSAPP_PROCESSING=false`, verify the Twilio credentials, and inspect outbound delivery status logs.
- Messages remain queued with `ASYNC_WHATSAPP_PROCESSING=true`: deploy a Celery worker using the same Redis URL.
- Twilio error `63007`: confirm `TWILIO_WHATSAPP_FROM` is the Sandbox or approved WhatsApp sender assigned to the account.
- Tester receives nothing: confirm that phone joined the Sandbox and that the WhatsApp conversation window is active.
- Credentials were pasted into git or a public log: rotate the Twilio Auth Token immediately, update Render, and redeploy the web service.

Free Render Postgres instances expire after 30 days, and free Key Value instances can lose session/cache data when restarted. Recreate or upgrade the database when it expires; a Key Value reset only resets chat sessions and cache, not Postgres data.
