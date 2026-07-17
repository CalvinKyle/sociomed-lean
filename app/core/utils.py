import time
import json
import logging
from dataclasses import dataclass
from typing import Optional, Dict, Any
import httpx
from tenacity import retry, stop_after_attempt, wait_exponential
import redis
from app.core.config import SESSION_TTL, SESSION_VERSION, WHATSAPP_TOKEN, PHONE_NUMBER_ID, build_redis_url
from app.core.states import ConversationState, is_valid_state

logger = logging.getLogger(__name__)

# Redis client for sessions + caching
redis_client = redis.Redis.from_url(build_redis_url(), decode_responses=True)
SEEN_MARKER_TTL_SECONDS = 60 * 60 * 24 * 30


@dataclass(frozen=True)
class WhatsAppSendResult:
    recipient: str
    success: bool
    status_code: Optional[int] = None
    provider_message_id: Optional[str] = None
    error: Optional[str] = None
    response_body: Optional[str] = None

    def to_audit_data(self) -> Dict[str, Any]:
        return {
            "recipient": self.recipient,
            "success": self.success,
            "status_code": self.status_code,
            "provider_message_id": self.provider_message_id,
            "error": self.error,
            "response_body": self.response_body[:500] if self.response_body else None,
        }


def _extract_whatsapp_message_id(response_body: str) -> Optional[str]:
    try:
        payload = json.loads(response_body)
    except json.JSONDecodeError:
        return None

    messages = payload.get("messages") or []
    if not messages:
        return None
    return messages[0].get("id")


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2))
async def send_whatsapp_message_result(to: str, message: str) -> WhatsAppSendResult:
    url = f"https://graph.facebook.com/v18.0/{PHONE_NUMBER_ID}/messages"
    headers = {"Authorization": f"Bearer {WHATSAPP_TOKEN}", "Content-Type": "application/json"}
    payload = {"messaging_product": "whatsapp", "to": to, "type": "text", "text": {"body": message}}
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            res = await client.post(url, headers=headers, json=payload)
        if res.status_code == 200:
            provider_message_id = _extract_whatsapp_message_id(res.text)
            logger.info("whatsapp_message_sent recipient=%s provider_message_id=%s", to, provider_message_id)
            return WhatsAppSendResult(
                recipient=to,
                success=True,
                status_code=res.status_code,
                provider_message_id=provider_message_id,
                response_body=res.text,
            )

        logger.error("whatsapp_message_failed recipient=%s status=%s response=%s", to, res.status_code, res.text[:500])
        return WhatsAppSendResult(
            recipient=to,
            success=False,
            status_code=res.status_code,
            error="whatsapp_api_error",
            response_body=res.text,
        )
    except Exception as e:
        logger.error("whatsapp_message_exception recipient=%s error=%s", to, e)
        raise


async def send_whatsapp_message(to: str, message: str) -> bool:
    result = await send_whatsapp_message_result(to, message)
    return result.success

# ── REDIS-BACKED SESSIONS (replaces old in-memory dict) ──
def save_session(user: str, data: Dict[str, Any]) -> None:
    key = f"session:{user}"
    data["_session_version"] = SESSION_VERSION
    redis_client.setex(key, SESSION_TTL, json.dumps(data))
    redis_client.setex(f"session_seen:{user}", SEEN_MARKER_TTL_SECONDS, "1")
    logger.info(f"Session saved for {user} (Redis)")


def has_seen_before(user: str) -> bool:
    return bool(redis_client.exists(f"session_seen:{user}"))


def get_session(user: str) -> Optional[Dict[str, Any]]:
    key = f"session:{user}"
    data = redis_client.get(key)
    if data:
        session = json.loads(data)
        if session.get("_session_version") != SESSION_VERSION:
            redis_client.delete(key)
            logger.info("Session version mismatch for %s - cleared stale session", user)
            return None
        return session
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

# ── MESSAGE DEDUPE (Meta redelivers webhook events on timeout/retry) ──
WHATSAPP_MESSAGE_DEDUPE_TTL_SECONDS = 60 * 60 * 24

def claim_whatsapp_message(message_id: Optional[str]) -> bool:
    """Atomically claim a WhatsApp message id for processing.

    Returns True the first time an id is seen (safe to process). Returns
    False if it was already claimed, meaning this is a duplicate webhook
    delivery that should be skipped. An empty id fails open (returns True)
    since we cannot dedupe without one.
    """
    if not message_id:
        return True
    key = f"wamid:{message_id}"
    return bool(redis_client.set(key, "1", nx=True, ex=WHATSAPP_MESSAGE_DEDUPE_TTL_SECONDS))

async def notify_vendor(vendor_phone: str, message: str) -> bool:
    if not vendor_phone:
        logger.warning("Vendor phone missing - cannot notify vendor")
        return False
    result = await send_whatsapp_message_result(vendor_phone, message)
    if not result.success:
        logger.error(f"Failed to notify vendor {vendor_phone}")
    return result.success

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
