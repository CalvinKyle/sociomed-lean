from app.core.utils import acquire_session_lock, release_session_lock
from app.services.whatsapp_service import handle_incoming_message


class WhatsAppMessageProcessingBusy(RuntimeError):
    pass


async def process_whatsapp_message_now(message: dict) -> None:
    sender = message.get("from", "unknown")
    if not acquire_session_lock(sender):
        raise WhatsAppMessageProcessingBusy(f"Session lock held for {sender}")

    try:
        await handle_incoming_message(message)
    finally:
        release_session_lock(sender)
