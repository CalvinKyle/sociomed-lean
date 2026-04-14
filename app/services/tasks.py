from app.core.celery_app import celery_app
from app.services.whatsapp_service import handle_incoming_message

@celery_app.task(name="process_whatsapp_message", bind=True, max_retries=3, default_retry_delay=5)
def process_whatsapp_message(self, message: dict):
    """Background task that processes the full WhatsApp message."""
    try:
        # Call the same handler we already have (no code duplication)
        import asyncio
        asyncio.run(handle_incoming_message(message))
    except Exception as exc:
        # Auto-retry on failure
        raise self.retry(exc=exc)
