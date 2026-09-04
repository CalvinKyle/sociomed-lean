# Twilio WhatsApp Beta Setup

The Twilio integration is configured through environment variables. Real credentials must be stored in Twilio and Render, never committed to git.

For low-volume Sandbox testing, set `ASYNC_WHATSAPP_PROCESSING=false`. The Render web service will process each inbound message directly and no paid Celery background worker is required. Redis remains required for conversation sessions, caching, sender locks, and duplicate-message protection.

## What Was Added

- `WHATSAPP_PROVIDER=twilio` switches outbound WhatsApp delivery from Meta Cloud API to Twilio.
- `POST /api/webhook/twilio` accepts Twilio's form-encoded inbound WhatsApp webhooks.
- `X-Twilio-Signature` is validated with the Twilio Auth Token before processing.
- `ASYNC_WHATSAPP_PROCESSING=false` runs the existing WhatsApp handler inside the web request.
- `ASYNC_WHATSAPP_PROCESSING=true` preserves the Celery queue and worker architecture for production.
- `POST /api/webhook/twilio/status` records Twilio delivery status callbacks in the audit log.
- Incoming Twilio payloads are translated into the existing SocioMed conversation flow, so catalog, RFQ, supplier notification, and sales handoff behavior stays unchanged.

Both modes use the same message-processing service and Redis session lock. If inline processing fails, the message's duplicate-protection claim is released and the webhook returns an error so Twilio can retry.

## 1. Get the Twilio Values

Open the [Twilio Console](https://console.twilio.com/) and collect these values:

| Environment variable | Where to find it | Example format |
| --- | --- | --- |
| `TWILIO_ACCOUNT_SID` | Account Dashboard / Account Info | `AC...` |
| `TWILIO_AUTH_TOKEN` | Account Dashboard / Account Info, reveal the primary Auth Token | Secret value; do not commit it |
| `TWILIO_WHATSAPP_FROM` | Messaging > Try it out > Send a WhatsApp message > Sandbox sender | `whatsapp:+14155238886` or the sender Twilio assigns |
| `TWILIO_WEBHOOK_URL` | Your deployed SocioMed URL plus the inbound path | `https://YOUR-SERVICE.onrender.com/api/webhook/twilio` |
| `TWILIO_STATUS_CALLBACK_URL` | Your deployed SocioMed URL plus the status path | `https://YOUR-SERVICE.onrender.com/api/webhook/twilio/status` |

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
TWILIO_ACCOUNT_SID=AC...
TWILIO_AUTH_TOKEN=your-real-primary-auth-token
TWILIO_WHATSAPP_FROM=whatsapp:+YOUR_TWILIO_SANDBOX_NUMBER
TWILIO_WEBHOOK_URL=https://YOUR-SERVICE.onrender.com/api/webhook/twilio
TWILIO_STATUS_CALLBACK_URL=https://YOUR-SERVICE.onrender.com/api/webhook/twilio/status
PUBLIC_BASE_URL=https://YOUR-SERVICE.onrender.com
```

Keep the existing Postgres, Redis, Google Sheets, `SALES_AGENT_PHONE`, and `API_KEY` production variables configured. Production startup validation still requires them.

You can suspend or omit the Celery worker during Sandbox testing. Do not remove Redis: the synchronous path still uses it for sessions, caching, duplicate-message claims, and sender locks.

The `render.yaml` web-service configuration now recommends `ASYNC_WHATSAPP_PROCESSING=false`. The Celery worker definition remains available for later production deployment.

## 4. Configure the Twilio Sandbox Webhook

1. Return to **Messaging > Try it out > Send a WhatsApp message**.
2. Open **Sandbox settings**.
3. In **When a message comes in**, enter the exact value used for `TWILIO_WEBHOOK_URL`.
4. Select `POST`.
5. Save the Sandbox configuration.

The URL in Twilio and `TWILIO_WEBHOOK_URL` must match exactly, including `https`, hostname, path, query string, and trailing slash behavior. Twilio includes the complete URL when calculating `X-Twilio-Signature`.

The application sends `TWILIO_STATUS_CALLBACK_URL` with every outbound message, so no separate Sandbox status URL is required.

## 5. Deploy Without a Celery Worker

The Render blueprint has `autoDeploy: false`, so deploy the updated branch or merged pull request manually:

1. Set `ASYNC_WHATSAPP_PROCESSING=false` on the web service.
2. Deploy `sociomed-lean`.
3. Leave the Celery worker suspended or undeployed for Sandbox testing.
4. Verify `GET https://YOUR-SERVICE.onrender.com/api/health/liveness` returns `{"status":"ok"}`.
5. Check the web-service logs for configuration errors before sending a WhatsApp message.

## 6. Beta Smoke Test

From a phone that joined the Sandbox:

1. Send `hello` to the Twilio Sandbox WhatsApp number.
2. Confirm the SocioMed main menu arrives.
3. Reply `1`, search for a product, and confirm results arrive.
4. Reply `3` and submit a sample RFQ.
5. Confirm the RFQ is saved and the supplier or sales notification is attempted.
6. Check Render logs for `twilio_whatsapp_delivery_status` audit events.

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
- Webhook returns `500`: inspect the web-service log. The message claim is released so a Twilio retry can process it again.
- Webhook returns `200` but no WhatsApp reply arrives: confirm `ASYNC_WHATSAPP_PROCESSING=false`, verify the Twilio credentials, and inspect outbound delivery status logs.
- Messages remain queued with `ASYNC_WHATSAPP_PROCESSING=true`: deploy a Celery worker using the same Redis URL.
- Twilio error `63007`: confirm `TWILIO_WHATSAPP_FROM` is the Sandbox or approved WhatsApp sender assigned to the account.
- Tester receives nothing: confirm that phone joined the Sandbox and that the WhatsApp conversation window is active.
- Credentials were pasted into git or a public log: rotate the Twilio Auth Token immediately, update Render, and redeploy the web service.
