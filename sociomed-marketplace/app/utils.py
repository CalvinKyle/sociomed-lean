import requests
import time
import json
import logging
from typing import Optional, Dict, Any
from tenacity import retry, stop_after_attempt, wait_exponential
from app.config import WHATSAPP_TOKEN, PHONE_NUMBER_ID

logger = logging.getLogger(__name__)


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2))
def send_whatsapp_message(to: str, message: str) -> bool:
    """Send WhatsApp message with retry logic and logging."""
    url = f"https://graph.facebook.com/v18.0/{PHONE_NUMBER_ID}/messages"
    
    headers = {
        "Authorization": f"Bearer {WHATSAPP_TOKEN}",
        "Content-Type": "application/json"
    }
    
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "text",
        "text": {"body": message}
    }
    
    try:
        res = requests.post(url, headers=headers, json=payload, timeout=10)
        
        if res.status_code == 200:
            logger.info(f"Message sent to {to}")
            return True
        else:
            logger.error(f"WhatsApp API error {res.status_code}: {res.text}")
            return False
    
    except Exception as e:
        logger.error(f"Error sending WhatsApp message to {to}: {e}")
        raise


# --- SESSION STORE (with expiry) ---
user_sessions: Dict[str, Dict[str, Any]] = {}
SESSION_TTL = 1800  # 30 minutes


def save_session(user: str, data: Dict[str, Any]) -> None:
    """Save user session with timestamp."""
    user_sessions[user] = {
        "data": data,
        "timestamp": time.time()
    }
    logger.info(f"Session saved for user {user}")


def get_session(user: str) -> Optional[Dict[str, Any]]:
    """Get user session if valid."""
    session = user_sessions.get(user)
    
    if not session:
        return None
    
    if time.time() - session["timestamp"] > SESSION_TTL:
        del user_sessions[user]
        logger.info(f"Session expired for user {user}")
        return None
    
    return session["data"]


def update_session(user: str, key: str, value: Any) -> None:
    """Update session value."""
    if user not in user_sessions:
        user_sessions[user] = {"data": {}, "timestamp": time.time()}
    
    user_sessions[user]["data"][key] = value
    user_sessions[user]["timestamp"] = time.time()
    logger.debug(f"Session updated for user {user}: {key}={value}")


def notify_vendor(vendor_phone: str, message: str) -> bool:
    """Notify vendor with error logging."""
    if not vendor_phone:
        logger.warning("Vendor phone number missing")
        return False
    
    success = send_whatsapp_message(vendor_phone, message)
    
    if not success:
        logger.error(f"Failed to notify vendor {vendor_phone}")
        # TODO: Implement message queue for retry
    
    return success


def log_audit_event(user_phone: str, event_type: str, data: Dict[str, Any]) -> None:
    """Log user action for audit trail."""
    audit_log = {
        "user_phone": user_phone,
        "event_type": event_type,
        "data": data,
        "timestamp": time.time()
    }
    logger.info(f"AUDIT: {json.dumps(audit_log)}")
