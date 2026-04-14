from fastapi import APIRouter, Request
from app.services.whatsapp_service import (
    extract_message,
    handle_incoming_message
)

router = APIRouter(prefix="/api")  # Optional prefix for future admin routes

# ── Health Check (required by Render & good practice) ──
@router.get("/health")
async def health_check():
    return {"status": "healthy", "service": "sociomed-lean"}

# ── WhatsApp Webhook Verification (GET) ──
@router.get("/webhook")
async def verify_webhook(mode: str = None, token: str = None, challenge: str = None):
    from app.core.config import VERIFY_TOKEN
    if token == VERIFY_TOKEN:
        return int(challenge)
    return {"status": "verification failed"}

# ── WhatsApp Incoming Messages (POST) ──
@router.post("/webhook")
async def whatsapp_webhook(req: Request):
    try:
        body = await req.json()
        message = await extract_message(body)

        if not message:
            return {"status": "ignored"}

        # All conversation logic is now cleanly handled in whatsapp_service
        await handle_incoming_message(message)
        return {"status": "ok"}

    except Exception as e:
        from app.core.utils import log_audit_event
        log_audit_event("system", "webhook_error", {"error": str(e)})
        return {"status": "error"}, 500
    except Exception as e:
        log_audit_event("system", "webhook_error", {"error": str(e)})
        return {"status": "error", "message": "Internal server error"}, 500
