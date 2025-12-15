import os
import json
import requests
import csv
import redis
import io
from flask import Flask, request, jsonify, Response
from sqlalchemy import create_engine, text
import time
import google.generativeai as genai
from typing import Dict, List, Tuple, Optional, Any
import logging
from datetime import datetime, timedelta
from collections import defaultdict
import uuid
from functools import wraps
from celery import Celery

# --- CONFIGURATION ---
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://sociomed_user:password@sociomed-database:5432/sociomed")
WHATSAPP_TOKEN = os.getenv("WHATSAPP_TOKEN")
PHONE_NUMBER_ID = os.getenv("PHONE_NUMBER_ID")
VERIFY_TOKEN = os.getenv("VERIFY_TOKEN", "your_verify_token")
WHATSAPP_API_VERSION = os.getenv("WHATSAPP_API_VERSION", "v19.0")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# --- INITIALIZE COMPONENTS ---
# Database
try:
    engine = create_engine(DATABASE_URL, pool_pre_ping=True, pool_recycle=3600)
    logger.info("Database engine initialized successfully")
except Exception as e:
    logger.error(f"Error initializing DB engine: {e}")
    engine = None

# Gemini AI
gemini_model = None
if GEMINI_API_KEY:
    try:
        genai.configure(api_key=GEMINI_API_KEY)
        gemini_model = genai.GenerativeModel('gemini-1.5-flash')
        logger.info("Gemini AI initialized successfully")
    except Exception as e:
        logger.error(f"Error initializing Gemini AI: {e}")

# --- REDIS CONNECTION (FOR PERSISTENT CARTS) ---
try:
    redis_client = redis.Redis(host='sociomed-redis', port=6379, db=0, decode_responses=True)
    redis_client.ping()  # Test connection
    logger.info("Redis connected successfully for persistent carts")
except Exception as e:
    logger.error(f"Redis connection failed: {e}")
    redis_client = None  # Fallback gracefully

# Celery setup
celery_app = Celery(
    'whatsapp_bot',
    broker='redis://sociomed-redis:6379/0',
    backend='redis://sociomed-redis:6379/0'
)

# --- USER & CART MANAGEMENT ---
class RedisCartManager:
    """Shopping cart that survives restarts using Redis"""
    
    def add_to_cart(self, phone: str, product_id: str, product_name: str, price: float, quantity: int = 1):
        key = f"cart:{phone}"
        item = {
            "product_id": product_id,
            "product_name": product_name,
            "price": price,
            "quantity": quantity,
            "added_at": datetime.utcnow().isoformat()
        }
        redis_client.rpush(key, json.dumps(item))
        redis_client.expire(key, 86400)  # Cart expires after 24 hours
        logger.info(f"Added {product_name} to cart for {phone}")

    def get_cart(self, phone: str):
        key = f"cart:{phone}"
        items_raw = redis_client.lrange(key, 0, -1)
        return [json.loads(item) for item in items_raw]

    def get_cart_summary(self, phone: str):
        items = self.get_cart(phone)
        if not items:
            return {"item_count": 0, "total": 0.0, "items": []}
        total = sum(item['price'] * item['quantity'] for item in items)
        return {
            "item_count": len(items),
            "total": total,
            "items": items
        }

    def clear_cart(self, phone: str):
        redis_client.delete(f"cart:{phone}")
        logger.info(f"Cleared cart for {phone}")

    def remove_from_cart(self, phone: str, item_index: int):
        """Remove item by position (0-based)"""
        key = f"cart:{phone}"
        redis_client.lrem(key, 1, redis_client.lindex(key, item_index))
        redis_client.expire(key, 86400)

# Use the new persistent cart
cart_manager = RedisCartManager()

# --- DATABASE SEARCH & DEMAND LOGGING ---
def search_master_database(query: str, limit: int = 5):
    if not gemini_model or not engine:
        return [], False

    try:
        # Create AI numbers for customer query
        query_emb = genai.embed_content(
            model="models/embedding-001",
            content=query,
            task_type="retrieval_query"
        )['embedding']

        with engine.connect() as conn:
            sql = text("""
                SELECT 
                    p.product_id, p.name, p.manufacturer, p.brand,
                    p.short_description, p.full_description, p.category, p.sku,
                    o.price, o.currency, s.name as supplier_name,
                    CASE WHEN o.in_stock THEN 'In Stock' ELSE 'Order on Demand' END as stock_status
                FROM products p
                JOIN product_offerings o ON p.product_id = o.product_id
                LEFT JOIN suppliers s ON o.supplier_id = s.supplier_id
                WHERE p.embedding IS NOT NULL
                ORDER BY p.embedding <-> :query_emb
                LIMIT :limit
            """)
            results = conn.execute(sql, {"query_emb": query_emb, "limit": limit}).fetchall()
            
            # Format results same as before...
            # (keep your existing product_dict formatting)
    except Exception as e:
        logger.error(f"Vector search error: {e}")
        return [], False

def format_products_for_whatsapp(products: List[Dict], include_pricing: bool = True) -> str:
    """Format product list with clear availability status"""
    if not products:
        return "No products found in our master database."
    
    message_lines = []
    message_lines.append(f"🔍 *Found {len(products)} result(s):*\n")
    
    for i, product in enumerate(products, 1):
        line = f"{i}. *{product['name']}*"
        
        if product.get('manufacturer'):
            line += f" by {product['manufacturer']}"
        
        # Availability & Logistics Logic
        if product['availability'] == 'IN_STOCK':
            line += f"\n   ✅ *In Stock* ({product['stock_qty']} units)"
            line += "\n   🚚 Ships: Immediately"
        elif product['availability'] == 'ORDER_ON_DEMAND':
            line += f"\n   📦 *Available on Order* (No Stock)"
            line += f"\n   ⏳ Lead Time: ~{product['lead_time']} days"
        else:
            line += "\n   ❌ Currently Unavailable"
        
        if include_pricing and product.get('price'):
            currency = product.get('currency', 'UGX')
            line += f"\n   💰 Price: {currency} {product['price']:,.0f}"
        
        if product.get('sku'):
            line += f"\n   🏷️ SKU: {product['sku']}"
        
        message_lines.append(line)
    
    return "\n".join(message_lines)

# --- RECOMMENDATION MOCK ---
def add_recommendations_to_response(response_text: str, product_ids: List[str]) -> str:
    # This acts as a placeholder for the recommendation engine
    return response_text

# --- AI & HANDLERS ---
def handle_simple_search(query: str, user_phone: str = None) -> Tuple[str, bool]:
    """Handle simple product searches with demand logging"""
    products, found_in_master = search_master_database(query, user_phone=user_phone)
    
    if not found_in_master:
        return (
            f"⚠️ We don't have '{query}' in our catalog yet.\n\n"
            "📝 I have logged this request with our procurement team. "
            "If we stock this item soon, we will notify you."
        ), False
    
    response = format_products_for_whatsapp(products, include_pricing=True)
    
    # Add quote instructions
    response += "\n\n" + "=" * 30 + "\n"
    response += "*ACTIONS:*\n"
    response += "• Reply 'ADD [Item Number]' to add to cart\n"
    response += "• Reply 'REQUEST QUOTE' for official PDF\n"
    
    return response, True

def handle_quote_command(phone: str, message: str) -> Optional[str]:
    message_lower = message.lower().strip()
    
    if message_lower.startswith('add '):
        # Logic to handle adding by name or ID could go here
        # For simplicity, we search and add the first result
        item_name = message[4:].strip()
        products, found = search_master_database(item_name, user_phone=phone, limit=1)
        
        if not found:
            return f"❌ '{item_name}' not found."
        
        product = products[0]
        item_id = cart_manager.add_to_cart(phone, product['product_id'], product['name'], product['price'])
        
        cart_summ = cart_manager.get_cart_summary(phone)
        return f"✅ Added *{product['name']}* to cart.\n📦 Total Items: {cart_summ['item_count']}"

    elif message_lower == 'cart':
        summ = cart_manager.get_cart_summary(phone)
        if summ['item_count'] == 0: return "Your cart is empty."
        msg = "🛒 *YOUR CART*\n"
        for item in summ['items']:
            msg += f"• {item['product_name']} (x{item['quantity']})\n"
        msg += f"\nTotal: {summ['total']:,.0f}"
        return msg
        
    elif message_lower == 'clear cart':
        cart_manager.clear_cart(phone)
        return "✅ Cart cleared."
        
    elif message_lower in ['request quote', 'quote']:
        summ = cart_manager.get_cart_summary(phone)
        if summ['item_count'] == 0: return "Cart is empty. Add items first."
        return "✅ Quote request received. Creating PDF..."
    
    return None

def detect_intent(message: str) -> Dict:
    message_lower = message.lower().strip()
    quote_keywords = ['quote', 'add', 'cart', 'remove', 'clear']
    if any(message_lower.startswith(kw) for kw in quote_keywords):
        return {'type': 'quote_command'}
    if message_lower in ['hello', 'hi', 'start', 'help']:
        return {'type': 'greeting'}
    return {'type': 'simple_search'}

# --- WHATSAPP API ---
def send_whatsapp_message(recipient_id: str, message: str) -> bool:
    try:
        headers = {
            "Authorization": f"Bearer {WHATSAPP_TOKEN}",
            "Content-Type": "application/json",
        }
        url = f"https://graph.facebook.com/{WHATSAPP_API_VERSION}/{PHONE_NUMBER_ID}/messages"
        payload = {
            "messaging_product": "whatsapp",
            "to": recipient_id,
            "type": "text",
            "text": {"body": message}
        }
        response = requests.post(url, headers=headers, json=payload, timeout=10)
        return response.status_code == 200
    except Exception as e:
        logger.error(f"Send failed: {e}")
        return False

# --- FLASK ROUTES ---
@app.route("/webhook", methods=["GET"])
def verify_webhook():
    mode = request.args.get("hub.mode")
    token = request.args.get("hub.verify_token")
    challenge = request.args.get("hub.challenge")
    if mode == "subscribe" and token == VERIFY_TOKEN:
        return challenge, 200
    return "Verification failed", 403

@app.route("/webhook", methods=["POST"])
def webhook():
    try:
        data = request.get_json(silent=True) or request.form
        if not data or data.get("object") != "whatsapp_business_account":
            return jsonify({"status": "ignored"}), 200
        
        for entry in data.get("entry", []):
            for change in entry.get("changes", []):
                if change.get("field") == "messages":
                    messages = change.get("value", {}).get("messages", [])
                    for message in messages:
                        recipient_id = message.get("from")
                        if message.get("type") == "text":
                            user_text = message.get("text", {}).get("body", "").strip()
                            
                            # 1. Check Quote Commands
                            quote_resp = handle_quote_command(recipient_id, user_text)
                            if quote_resp:
                                send_whatsapp_message(recipient_id, quote_resp)
                                continue

                            # 2. Check Intent
                            intent = detect_intent(user_text)
                            
                            if intent["type"] == "greeting":
                                resp = "👋 Welcome to SocioMed! Type a product name to search."
                                send_whatsapp_message(recipient_id, resp)
                            
                            elif intent["type"] == "simple_search":
                                # Pass recipient_id for demand logging
                                resp, _ = handle_simple_search(user_text, user_phone=recipient_id)
                                send_whatsapp_message(recipient_id, resp)
                            
        return jsonify({"status": "processed"}), 200
    except Exception as e:
        logger.error(f"Webhook error: {e}")
        return jsonify({"status": "error"}), 500

# --- ADMIN REPORTING ENDPOINT (NEW) ---
@app.route("/admin/demand-report", methods=["GET"])
def download_demand_report():
    """Generates a CSV file tallying requests for items not in stock"""
    # In production, add a secret token check (e.g., ?token=ADMIN_SECRET)
    
    sql = text("""
        SELECT 
            search_term, 
            demand_type, 
            COUNT(*) as request_count,
            MAX(created_at) as last_requested
        FROM unmet_demand
        GROUP BY search_term, demand_type
        ORDER BY request_count DESC
    """)
    
    try:
        with engine.connect() as conn:
            results = conn.execute(sql).fetchall()
            
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(['Search Term', 'Status', 'Total Requests', 'Last Requested'])
        
        for row in results:
            writer.writerow([row.search_term, row.demand_type, row.request_count, row.last_requested])
            
        return Response(
            output.getvalue(),
            mimetype="text/csv",
            headers={"Content-disposition": "attachment; filename=market_demand_tally.csv"}
        )
    except Exception as e:
        return f"Error generating report: {e}", 500

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
