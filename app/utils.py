import requests
import time
import json
import logging
from typing import Optional, Dict, Any
from tenacity import retry, stop_after_attempt, wait_exponential
import redis
from app.config import REDIS_HOST, REDIS_PORT, SESSION_TTL, WHATSAPP_TOKEN, PHONE_NUMBER_ID

logger = logging.getLogger(__name__)

# Redis client for sessions + caching
redis_client = redis.StrictRedis(host=REDIS_HOST, port=REDIS_PORT, decode_responses=True)

@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2))
def send_whatsapp_message(to: str, message: str) -> bool:
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

def notify_vendor(vendor_phone: str, message: str) -> bool:
    # (same as before)
    if not vendor_phone:
        logger.warning("Vendor phone missing")
        return False
    success = send_whatsapp_message(vendor_phone, message)
    if not success:
        logger.error(f"Failed to notify vendor {vendor_phone}")
    return success

def log_audit_event(user_phone: str, event_type: str, data: Dict[str, Any]) -> None:
    # (same as before)
    audit_log = {"user_phone": user_phone, "event_type": event_type, "data": data, "timestamp": time.time()}
    logger.info(f"AUDIT: {json.dumps(audit_log)}")
