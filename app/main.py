from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from slowapi import Limiter
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
import logging
import hmac
import hashlib
from typing import Optional, Dict, Any

from app.config import VERIFY_TOKEN, validate_config, WHATSAPP_APP_SECRET
from app.logging_config import setup_logging
from app.sheets import load_data
from app.search import find_product, get_results
from app.formatter import format_results
from app.utils import (
    send_whatsapp_message,
    save_session,
    get_session,
    update_session,
    notify_vendor,
    log_audit_event
)
from app.redis_session import RedisSessionManager
from prometheus_client import Counter, Histogram, generate_latest
from app.models import PFIRequest

# Setup logging
setup_logging()
logger = logging.getLogger(__name__)

# Initialize FastAPI
app = FastAPI(title="SocioMed Marketplace", version="2.0.0")
@app.get("/health")
def health():
    return {"status": "healthy"}

# Rate limiting
limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter

# Redis session manager
redis_session = RedisSessionManager()

# Metrics
webhook_requests = Counter('webhook_requests_total', 'Total webhook requests')
webhook_errors = Counter('webhook_errors_total', 'Webhook errors')
sheets_load_time = Histogram('sheets_load_seconds', 'Time to load sheets')

# Validate config at startup
validate_config()
logger.info("Application initialized successfully")


@app.get("/health")
def health() -> Dict[str, str]:
    """Health check endpoint."""
    try:
        data = load_data()
        return {
            "status": "healthy",
            "sheets": "accessible",
            "data_items": len(data.get("products", []))
        }
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        return {"status": "unhealthy", "error": str(e)}, 503


@app.get("/metrics")
def metrics():
    """Prometheus metrics endpoint."""
    return generate_latest()


@app.get("/webhook")
def verify(mode: Optional[str] = None, token: Optional[str] = None, challenge: Optional[str] = None) -> int:
    """Webhook verification endpoint."""
    if token == VERIFY_TOKEN:
        logger.info("Webhook verified successfully")
        return int(challenge)
    
    logger.warning(f"Webhook verification failed with token: {token}")
    return {"status": "Verification failed"}, 403


def verify_whatsapp_signature(req_body: bytes, signature: str) -> bool:
    """Verify WhatsApp webhook signature."""
    if not WHATSAPP_APP_SECRET:
        logger.warning("WHATSAPP_APP_SECRET not configured, skipping verification")
        return True
    
    hash_obj = hmac.new(
        WHATSAPP_APP_SECRET.encode('utf-8'),
        msg=req_body,
        digestmod=hashlib.sha256
    )
    expected_hash = "sha256=" + hash_obj.hexdigest()
    
    return hmac.compare_digest(signature, expected_hash)


def extract_message(body: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Safely extract message from webhook payload."""
    try:
        return body["entry"][0]["changes"][0]["value"]["messages"][0]
    except (KeyError, IndexError, TypeError):
        return None


@app.post("/webhook")
@limiter.limit("100/minute")
async def webhook(req: Request) -> Dict[str, str]:
    """Main webhook handler."""
    webhook_requests.inc()
    
    try:
        # Verify signature
        signature = req.headers.get("X-Hub-Signature-256", "")
        req_body = await req.body()
        
        if not verify_whatsapp_signature(req_body, signature):
            logger.warning("Invalid webhook signature")
            return {"status": "unauthorized"}, 403
        
        body = await req.json()
        message = extract_message(body)
        
        if not message:
            logger.debug("Ignoring non-message event")
            return {"status": "ignored"}
        
        text = message.get("text", {}).get("body", "").strip().lower()
        sender = message["from"]
        
        if not text:
            logger.warning(f"Empty message from {sender}")
            send_whatsapp_message(sender, "Please send a product name.")
            return {"status": "ok"}
        
        session = get_session(sender)
        
        # === PFI FLOW ===
        if session and text == "1":
            update_session(sender, "stage", "pfi_name")
            log_audit_event(sender, "pfi_started", {})
            send_whatsapp_message(sender, "Enter facility name:")
            return {"status": "ok"}
        
        if session and session.get("stage") == "pfi_name":
            update_session(sender, "facility_name", text)
            update_session(sender, "stage", "pfi_location")
            send_whatsapp_message(sender, "Enter delivery location:")
            return {"status": "ok"}
        
        if session and session.get("stage") == "pfi_location":
            update_session(sender, "location", text)
            update_session(sender, "stage", "pfi_quantity")
            send_whatsapp_message(sender, "Enter required quantity:")
            return {"status": "ok"}
        
        if session and session.get("stage") == "pfi_quantity":
            try:
                quantity = int(text)
                if quantity <= 0:
                    send_whatsapp_message(sender, "Please enter a positive number.")
                    return {"status": "ok"}
            except ValueError:
                send_whatsapp_message(sender, "Please enter a valid number.")
                return {"status": "ok"}
            
            update_session(sender, "quantity", quantity)
            
            summary = (
                "*PFI REQUEST*\n\n"
                f"Product: {session['product']['name']}\n"
                f"Quantity: {quantity}\n"
                f"Facility: {session['facility_name']}\n"
                f"Location: {session['location']}\n"
            )
            
            send_whatsapp_message(sender, summary + "\nSubmitted to supplier.")
            
            # Smart routing: select best price option
            best_option = min(
                session["options"],
                key=lambda o: min(
                    (tier["unit_price"] for item in o["items"] for tier in item["pricing"]),
                    default=float('inf')
                )
            )
            
            first_vendor = best_option["items"][0]
            notify_vendor(first_vendor["vendor_phone"], summary)
            
            log_audit_event(sender, "pfi_submitted", {
                "product_id": session['product']['product_id'],
                "quantity": quantity,
                "vendor_id": first_vendor["vendor_id"]
            })
            
            return {"status": "ok"}
        
        # === RECOMMENDATION ===
        if session and text == "2":
            best_option = min(
                session["options"],
                key=lambda o: min(
                    (tier["unit_price"] for item in o["items"] for tier in item["pricing"]),
                    default=float('inf')
                )
            )
            
            send_whatsapp_message(
                sender,
                f"Best option: {best_option['brand']} (Option {best_option['option']})"
            )
            
            log_audit_event(sender, "recommendation_requested", {
                "product_id": session['product']['product_id'],
                "selected_brand": best_option['brand']
            })
            
            return {"status": "ok"}
        
        # === NEW SEARCH ===
        data = load_data()
        
        product = find_product(text, data["products"], data["aliases"])
        
        if not product:
            logger.info(f"Product not found for query: {text}")
            send_whatsapp_message(sender, "Product not found. Try another name.")
            log_audit_event(sender, "product_search_failed", {"query": text})
            return {"status": "ok"}
        
        results = get_results(product["product_id"], data)
        
        if not results:
            send_whatsapp_message(sender, "No available vendors for this product.")
            return {"status": "ok"}
        
        reply, option_map = format_results(product["name"], results)
        
        save_session(sender, {
            "product": product,
            "options": option_map
        })
        
        send_whatsapp_message(sender, reply)
        
        log_audit_event(sender, "product_searched", {
            "product_id": product["product_id"],
            "product_name": product["name"],
            "options_count": len(option_map)
        })
        
        return {"status": "ok"}
    
    except Exception as e:
        webhook_errors.inc()
        logger.error(f"Webhook error: {e}", exc_info=True)
        try:
            await send_whatsapp_message(sender, "Service error. Please try again later.")
        except:
            pass
        return {"status": "error"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
