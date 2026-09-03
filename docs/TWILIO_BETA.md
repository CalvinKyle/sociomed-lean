# Twilio WhatsApp Beta Setup

The Twilio integration is configured through environment variables. Real credentials must be stored in Twilio and Render, never committed to git.

## What Was Added

- `WHATSAPP_PROVIDER=twilio` switches outbound WhatsApp delivery from Meta Cloud API to Twilio.
- `POST /api/webhook/twilio` accepts Twilio's form-encoded inbound WhatsApp webhooks.
- `X-Twilio-Signature` is validated with the Twilio Auth Token before a message is queued.
- `POST /api/webhook/twilio/status` records Twilio delivery status callbacks in the audit log.
- Incoming Twilio payloads are translated into the existing SocioMed conversation flow, so the catalog, RFQ, supplier notification, and sales handoff behavior stays unchanged.

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

## 3. Add Secrets in Render

In the Render dashboard, open each service and go to **Environment**.

Set these on `sociomed-lean` and `sociomed-lean-celery-worker`:

```text
WHATSAPP_PROVIDER=twilio
TWILIO_ACCOUNT_SID=AC...
TWILIO_AUTH_TOKEN=your-real-primary-auth-token
TWILIO_WHATSAPP_FROM=whatsapp:+YOUR_TWILIO_SANDBOX_NUMBER
TWILIO_WEBHOOK_URL=https://YOUR-SERVICE.onrender.com/api/webhook/twilio
TWILIO_STATUS_CALLBACK_URL=https://YOUR-SERVICE.onrender.com/api/webhook/twilio/status
PUBLIC_BASE_URL=https://YOUR-SERVICE.onrender.com
```

Set the outbound Twilio values on `sociomed-lean-celery-beat` too if the scheduled RFQ digest remains enabled.

Keep the existing Postgres, Redis, Google Sheets, `SALES_AGENT_PHONE`, and `API_KEY` production variables configured. Production startup validation still requires them.

The `render.yaml` blueprint now contains `sync: false` secret slots. Render will prompt for these values during a new Blueprint deployment, or you can enter them manually in each service's Environment page.

## 4. Configure the Twilio Sandbox Webhook

1. Return to **Messaging > Try it out > Send a WhatsApp message**.
2. Open **Sandbox settings**.
3. In **When a message comes in**, enter the exact value used for `TWILIO_WEBHOOK_URL`.
4. Select `POST`.
5. Save the Sandbox configuration.

The URL in Twilio and `TWILIO_WEBHOOK_URL` must match exactly, including `https`, hostname, path, query string, and trailing slash behavior. Twilio includes the complete URL when calculating `X-Twilio-Signature`.

The application sends `TWILIO_STATUS_CALLBACK_URL` with every outbound message, so no separate Sandbox status URL is required.

## 5. Deploy

The Render blueprint has `autoDeploy: false`, so deploy the updated branch or merged pull request manually:

1. Deploy `sociomed-lean`.
2. Deploy `sociomed-lean-celery-worker`.
3. Deploy `sociomed-lean-celery-beat` if it is enabled.
4. Verify `GET https://YOUR-SERVICE.onrender.com/api/health/liveness` returns `{"status":"ok"}`.
5. Check the web and worker logs for configuration errors before sending a WhatsApp message.

## 6. Beta Smoke Test

From a phone that joined the Sandbox:

1. Send `hello` to the Twilio Sandbox WhatsApp number.
2. Confirm the SocioMed main menu arrives.
3. Reply `1`, search for a product, and confirm results arrive.
4. Reply `3` and submit a sample RFQ.
5. Confirm the RFQ is saved and the supplier or sales notification is attempted.
6. Check Render logs for `twilio_whatsapp_delivery_status` audit events.

Twilio/WhatsApp free-form replies are intended for the active customer-service conversation window. For proactive messages outside that window, configure approved WhatsApp Content Templates before production use.

## Local Testing With ngrok

For local testing only:

```bash
uvicorn app.main:app --reload
celery -A app.core.celery_app worker --loglevel=info
ngrok http 8000
```

Copy `.env.example` to `.env.local`, replace the ngrok placeholder with the current HTTPS forwarding hostname, and use that exact URL in Twilio Sandbox settings. Restart the API after changing `.env.local`.

## Troubleshooting

- `403 invalid Twilio webhook signature`: confirm the primary Auth Token is correct and the configured webhook URL exactly matches Twilio's URL.
- Webhook returns `200` but no WhatsApp reply arrives: confirm the Celery worker is running and has the same Twilio and Redis values as the web service.
- Twilio error `63007`: confirm `TWILIO_WHATSAPP_FROM` is the Sandbox or approved WhatsApp sender assigned to the account.
- Tester receives nothing: confirm that phone joined the Sandbox and that the WhatsApp conversation window is active.
- Credentials were pasted into git or a public log: rotate the Twilio Auth Token immediately, update Render, and redeploy the web and worker services.
