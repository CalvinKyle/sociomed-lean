import requests
import time
import json
import logging
from typing import Optional, Dict, Any
from tenacity import retry, stop_after_attempt, wait_exponential
import redis
from app.core.config import SESSION_TTL, WHATSAPP_TOKEN, PHONE_NUMBER_ID, build_redis_url
from app.core.states import ConversationState, is_valid_state

logger = logging.getLogger(__name__)

# Redis client for sessions + caching
redis_client = redis.Redis.from_url(build_redis_url(), decode_responses=True)

@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2))
async def send_whatsapp_message(to: str, message: str) -> bool:
    # (same code as before — unchanged)
    url = f"https://graph.facebook.com/v18.0/{PHONE_NUMBER_ID}/messages"
    headers = {"Authorization": f"Bearer {WHATSAPP_TOKEN}", "Content-Type": "application/json"}
    payload = {"messaging_product": "whatsapp", "to": to, "type": "text", "text": {"body": message}}
    try:
        res = requests.post(url, headers=headers, json=payload, timeout=10)
        if res.status_code == 200:
            logger.info(f"Message sent to {to}")
            return True
        else:
            logger.error(f"WhatsApp API error {res.status_code}: {res.text}")
            return False
    except Exception as e:
        logger.error(f"Error sending to {to}: {e}")
        raise

# ── REDIS-BACKED SESSIONS (replaces old in-memory dict) ──
def save_session(user: str, data: Dict[str, Any]) -> None:
    key = f"session:{user}"
    redis_client.setex(key, SESSION_TTL, json.dumps(data))
    logger.info(f"Session saved for {user} (Redis)")

def get_session(user: str) -> Optional[Dict[str, Any]]:
    key = f"session:{user}"
    data = redis_client.get(key)
    if data:
        return json.loads(data)
    return None

def update_session(user: str, key: str, value: Any) -> None:
    session = get_session(user) or {}
    session[key] = value
    save_session(user, session)
    logger.debug(f"Session updated for {user}: {key}={value}")

def delete_session(user: str) -> None:
    key = f"session:{user}"
    redis_client.delete(key)
    logger.info(f"Session deleted for {user}")

# ── SESSION LOCKS (prevents race conditions on duplicate webhooks) ──
def acquire_session_lock(user: str, timeout: int = 10) -> bool:
    lock_key = f"session_lock:{user}"
    return bool(redis_client.set(lock_key, "1", ex=timeout, nx=True))

def release_session_lock(user: str) -> None:
    redis_client.delete(f"session_lock:{user}")

async def notify_vendor(vendor_phone: str, message: str) -> bool:
    if not vendor_phone:
        logger.warning("Vendor phone missing - cannot notify vendor")
        return False
    success = await send_whatsapp_message(vendor_phone, message)
    if not success:
        logger.error(f"Failed to notify vendor {vendor_phone}")
    return success

def log_audit_event(user_phone: str, event_type: str, data: Dict[str, Any]) -> None:
    # (same as before)
    audit_log = {"user_phone": user_phone, "event_type": event_type, "data": data, "timestamp": time.time()}
    logger.info(f"AUDIT: {json.dumps(audit_log)}")

def set_state(user: str, state: str):
    """Helper to set the current conversation state (used by the strict state machine)"""
    session = get_session(user) or {}
    session["state"] = state
    save_session(user, session)

def get_current_state(user: str) -> str:
    """Helper to get the current conversation state"""
    session = get_session(user)
    if not session:
        return ConversationState.MENU.value
    state = session.get("state", ConversationState.MENU.value)
    return state if is_valid_state(state) else ConversationState.MENU.value
