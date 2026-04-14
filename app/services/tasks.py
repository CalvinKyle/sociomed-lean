from app.core.celery_app import celery_app
from app.services.whatsapp_service import handle_incoming_message
from app.core.utils import acquire_session_lock, release_session_lock
import asyncio

@celery_app.task(name="process_whatsapp_message", bind=True, max_retries=3, default_retry_delay=5)
def process_whatsapp_message(self, message: dict):
    """Background task that processes the full WhatsApp message."""
    sender = message["from"]

    # ── Prevent race conditions from duplicate Meta webhook deliveries ──
    if not acquire_session_lock(sender):
        raise self.retry(countdown=2)  # Another worker is handling this user, back off

    try:
        asyncio.run(handle_incoming_message(message))
    except Exception as exc:
        raise self.retry(exc=exc)
    finally:
        release_session_lock(sender)  # Always release, even if task fails
