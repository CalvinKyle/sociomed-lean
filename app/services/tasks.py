import asyncio
from app.core.celery_app import celery_app
from app.services.whatsapp_service import handle_incoming_message
from app.core.utils import acquire_session_lock, release_session_lock
import logging

logger = logging.getLogger(__name__)

# One shared event loop per worker process — not one per task
_loop = asyncio.new_event_loop()


@celery_app.task(
    name="process_whatsapp_message",
    bind=True,
    max_retries=3,
    default_retry_delay=5,
    acks_late=True       # Only ack after task completes — prevents lost messages on crash
)
def process_whatsapp_message(self, message: dict):
    sender = message.get("from", "unknown")
    
    if not acquire_session_lock(sender):
        logger.info(f"Session lock held for {sender} — retrying in 2s")
        raise self.retry(countdown=2)
    
    try:
        _loop.run_until_complete(handle_incoming_message(message))
    except Exception as exc:
        logger.error(f"Task failed for {sender}: {exc}")
        raise self.retry(exc=exc)
    finally:
        release_session_lock(sender)
