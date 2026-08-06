from app.core.celery_app import celery_app
from celery import Task

from app.services.rfq_digest import send_daily_rfq_digest as deliver_daily_rfq_digest
from app.services.whatsapp_service import handle_incoming_message
from app.core.utils import acquire_session_lock, log_audit_event, release_session_lock, send_whatsapp_message
import logging
import asyncio

logger = logging.getLogger(__name__)

FALLBACK_MESSAGE = (
    "Sorry, I could not complete that request right now. Your message has not been ignored. "
    "Please try again shortly, or reply 3 from the main menu to contact sales."
)


class WhatsAppMessageTask(Task):
    def on_failure(self, exc, task_id, args, kwargs, einfo):
        message = args[0] if args else kwargs.get("message", {})
        sender = message.get("from", "unknown") if isinstance(message, dict) else "unknown"
        fallback_sent = False
        if sender != "unknown":
            try:
                fallback_sent = asyncio.run(send_whatsapp_message(sender, FALLBACK_MESSAGE))
            except Exception:
                logger.exception("whatsapp_task_fallback_failed sender=%s task_id=%s", sender, task_id)
        log_audit_event(
            sender,
            "whatsapp_task_hard_failure",
            {"task_id": task_id, "error": str(exc), "fallback_sent": fallback_sent},
        )
        super().on_failure(exc, task_id, args, kwargs, einfo)


@celery_app.task(
    name="process_whatsapp_message",
    bind=True,
    max_retries=3,
    default_retry_delay=5,
    acks_late=True,      # Only ack after task completes — prevents lost messages on crash
    base=WhatsAppMessageTask,
)
def process_whatsapp_message(self, message: dict):
    sender = message.get("from", "unknown")
    
    if not acquire_session_lock(sender):
        logger.info(f"Session lock held for {sender} — retrying in 2s")
        raise self.retry(countdown=2)
    
    try:
        asyncio.run(handle_incoming_message(message))
    except Exception as exc:
        logger.error(f"Task failed for {sender}: {exc}")
        log_audit_event(
            sender,
            "whatsapp_task_attempt_failed",
            {"task_id": self.request.id, "attempt": self.request.retries + 1, "error": str(exc)},
        )
        raise self.retry(exc=exc)
    finally:
        release_session_lock(sender)


@celery_app.task(name="send_daily_rfq_digest")
def send_daily_rfq_digest():
    return asyncio.run(deliver_daily_rfq_digest())
