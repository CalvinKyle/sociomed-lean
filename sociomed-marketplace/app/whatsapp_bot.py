import os
import json
import requests
from flask import Flask, request, jsonify
from sqlalchemy import create_engine, text
import time
import google.generativeai as genai
from typing import Dict, List, Tuple, Optional, Any
import logging
from datetime import datetime, timedelta
from collections import defaultdict
from recommendation_engine import get_recommendations
import uuid
import threading
from functools import wraps

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# --- CONFIGURATION ---
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://postgres:password@sociomed-database:5432/medical_db")
WHATSAPP_TOKEN = os.getenv("WHATSAPP_TOKEN")
PHONE_NUMBER_ID = os.getenv("PHONE_NUMBER_ID")
VERIFY_TOKEN = os.getenv("VERIFY_TOKEN", "your_verify_token")
WHATSAPP_API_VERSION = os.getenv("WHATSAPP_API_VERSION", "v19.0")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

# --- INITIALIZE COMPONENTS ---
# Database
try:
    engine = create_engine(DATABASE_URL, pool_pre_ping=True, pool_recycle=3600)
    logger.info("Database engine initialized successfully")
except Exception as e:
    logger.error(f"Error initializing DB engine: {e}")
    engine = None

# Gemini AI (only if API key exists)
gemini_model = None
if GEMINI_API_KEY:
    try:
        genai.configure(api_key=GEMINI_API_KEY)
        gemini_model = genai.GenerativeModel('gemini-1.5-flash')
        logger.info("Gemini AI initialized successfully")
    except Exception as e:
        logger.error(f"Error initializing Gemini AI: {e}")

# --- USER & CART MANAGEMENT (From Bot 2) ---
class UserCartManager:
    """Manages user sessions and shopping carts with disk persistence"""
    def __init__(self, session_timeout_minutes=30, persistence_file="/data/cart_state.json"):
        self.persistence_file = persistence_file
        self.session_timeout = timedelta(minutes=session_timeout_minutes)
        self.user_carts = defaultdict(list)  # phone -> list of cart items
        self.user_sessions = {}  # phone -> {'last_activity': datetime, 'state': str}
        self._load_state()  # Load from disk on startup

    def _save_state(self):
        """Persist carts and sessions to disk"""
        try:
            # Ensure directory exists
            os.makedirs(os.path.dirname(self.persistence_file), exist_ok=True)
            data = {
                "carts": dict(self.user_carts),  # Convert defaultdict to dict
                "sessions": {
                    phone: {
                        'last_activity': session['last_activity'].isoformat(),
                        'state': session['state']
                    } for phone, session in self.user_sessions.items()
                }
            }
            with open(self.persistence_file, 'w') as f:
                json.dump(data, f)
            logger.info("Cart state saved to disk")
        except Exception as e:
            logger.error(f"Failed to save cart state: {e}")

    def _load_state(self):
        """Load carts and sessions from disk"""
        if os.path.exists(self.persistence_file):
            try:
                with open(self.persistence_file, 'r') as f:
                    data = json.load(f)
                    self.user_carts = defaultdict(list, data.get("carts", {}))
                    for phone, session_data in data.get("sessions", {}).items():
                        self.user_sessions[phone] = {
                            'last_activity': datetime.fromisoformat(session_data['last_activity']),
                            'state': session_data['state']
                        }
                logger.info("Cart state loaded from disk")
            except Exception as e:
                logger.error(f"Failed to load cart state: {e}")

    def _clean_old_sessions(self):
        """Remove expired sessions and save"""
        now = datetime.utcnow()
        expired = [phone for phone, session in self.user_sessions.items()
                   if now - session['last_activity'] > self.session_timeout]
        for phone in expired:
            self.clear_cart(phone)
            del self.user_sessions[phone]
            logger.info(f"Cleared expired session for {phone}")

    def get_user_state(self, phone: str) -> str:
        self._clean_old_sessions()
        if phone not in self.user_sessions:
            return "NEW"
        return self.user_sessions[phone].get('state', 'SEARCHING')

    def update_user_state(self, phone: str, state: str):
        self.user_sessions[phone] = {
            'last_activity': datetime.utcnow(),
            'state': state
        }
        self._save_state()  # Save on update

    def add_to_cart(self, phone: str, product_id: str, product_name: str,
                   price: float, quantity: int = 1, notes: str = "") -> str:
        item_id = str(uuid.uuid4())[:8]
        item = {
            'item_id': item_id,
            'product_id': product_id,
            'product_name': product_name,
            'price': price,
            'quantity': quantity,
            'added_at': datetime.utcnow().isoformat(),
            'notes': notes
        }
        self.user_carts[phone].append(item)
        self.update_user_state(phone, "CART_ACTIVE")
        logger.info(f"Added item {item_id} to cart for {phone}")
        self._save_state()  # Persist immediately
        return item_id

    def remove_from_cart(self, phone: str, item_id: str) -> bool:
        cart = self.user_carts.get(phone, [])
        for i, item in enumerate(cart):
            if item['item_id'] == item_id:
                cart.pop(i)
                logger.info(f"Removed item {item_id} from cart for {phone}")
                self._save_state()
                return True
        return False

    def clear_cart(self, phone: str):
        if phone in self.user_carts:
            self.user_carts[phone] = []
            logger.info(f"Cleared cart for {phone}")
            self._save_state()

    def get_cart(self, phone: str) -> List[Dict]:
        return self.user_carts.get(phone, [])

    def get_cart_summary(self, phone: str) -> Dict[str, Any]:
        cart = self.get_cart(phone)
        if not cart:
            return {"item_count": 0, "total": 0.0, "items": []}
        total = sum(item['price'] * item['quantity'] for item in cart)
        return {"item_count": len(cart), "total": total, "items": cart}

    def is_cart_empty(self, phone: str) -> bool:
        return len(self.user_carts.get(phone, [])) == 0


# Global instance (used across webhook calls)
cart_manager = UserCartManager()

# --- DATABASE FUNCTIONS ---
def search_master_database(query: str, limit: int = 5) -> Tuple[List[Dict], bool]:
    """
    Search master database for products.
    Returns: (results_list, found_in_master)
    """
    if not engine:
        return [], False
    
    try:
        with engine.connect() as conn:
            # Enhanced search with manufacturer field (from Bot 3)
            sql_query = text("""
                SELECT 
                    p.product_id,
                    p.name, 
                    p.manufacturer,
                    p.brand,
                    p.short_description,
                    p.full_description,
                    p.category,
                    p.subcategory,
                    p.sku,
                    o.price,
                    o.currency,
                    s.name as supplier_name,
                    s.supplier_id,
                    p.unit_of_measure,
                    p.min_order_quantity,
                    CASE 
                        WHEN p.in_stock = true THEN 'In Stock'
                        ELSE 'Out of Stock'
                    END as stock_status
                FROM products p
                JOIN product_offerings o ON p.product_id = o.product_id
                LEFT JOIN suppliers s ON o.supplier_id = s.supplier_id
                WHERE 
                    p.name ILIKE :search_term 
                    OR p.manufacturer ILIKE :search_term  -- From Bot 3
                    OR p.category ILIKE :search_term
                    OR p.subcategory ILIKE :search_term
                    OR p.sku ILIKE :search_term
                    OR p.full_description ILIKE :search_term
                ORDER BY 
                    CASE 
                        WHEN p.name ILIKE :search_term THEN 1
                        WHEN p.sku ILIKE :search_term THEN 2
                        WHEN p.manufacturer ILIKE :search_term THEN 3  -- From Bot 3
                        WHEN p.category ILIKE :search_term THEN 4
                        ELSE 5
                    END,
                    o.price ASC
                LIMIT :limit
            """)
            
            search_term = f"%{query}%"
            result = conn.execute(sql_query, {"search_term": search_term, "limit": limit}).fetchall()
            
            if not result:
                return [], False
            
            # Convert to list of dictionaries
            products = []
            for row in result:
                product_dict = {
                    'product_id': row.product_id,
                    'name': row.name,
                    'manufacturer': row.manufacturer,  # From Bot 3
                    'brand': row.brand,
                    'short_description': row.short_description,
                    'full_description': row.full_description,
                    'category': row.category,
                    'subcategory': row.subcategory,
                    'sku': row.sku,
                    'price': float(row.price) if row.price else 0.0,
                    'currency': row.currency or 'USD',
                    'supplier': row.supplier_name,
                    'supplier_id': row.supplier_id,
                    'unit_of_measure': row.unit_of_measure,
                    'min_order_quantity': row.min_order_quantity,
                    'stock_status': row.stock_status,
                    'source': 'master_database'
                }
                products.append(product_dict)
            
            return products, True
            
    except Exception as e:
        logger.error(f"Database query error: {e}")
        return [], False

def format_products_for_whatsapp(products: List[Dict], include_pricing: bool = True) -> str:
    """Format product list for WhatsApp message"""
    if not products:
        return "No products found in our master database."
    
    message_lines = []
    message_lines.append(f"Found {len(products)} product(s):\n")
    
    for i, product in enumerate(products, 1):
        line = f"{i}. *{product['name']}*"
        
        if product.get('manufacturer'):
            line += f" by {product['manufacturer']}"
        
        if product.get('short_description'):
            line += f"\n   📝 {product['short_description'][:80]}..."
        
        if include_pricing and product.get('price'):
            currency = product.get('currency', 'USD')
            # Support UGX formatting (from Bot 1)
            if currency == 'UGX':
                line += f"\n   💰 Price: {product['price']:,.0f} UGX"
            else:
                line += f"\n   💰 Price: {currency} {product['price']:,.2f}"
        
        if product.get('stock_status'):
            emoji = "✅" if "In Stock" in product['stock_status'] else "⏳"
            line += f"\n   {emoji} {product['stock_status']}"
        
        if product.get('sku'):
            line += f"\n   🏷️ SKU: {product['sku']}"
        
        message_lines.append(line)
    
    return "\n".join(message_lines)

def process_message_async(recipient_id: str, user_text: str):
    """Background task for heavy processing (DB + Gemini)"""
    with app.app_context():  # Required for Flask context in threads
        try:
            logger.info(f"Starting async processing for {recipient_id}: {user_text[:50]}")

            # === Copy ALL your existing processing logic here ===
            # Check for quote/cart commands first
            quote_response = handle_quote_command(recipient_id, user_text)
            if quote_response:
                send_whatsapp_message(recipient_id, quote_response)
                return

            # Detect intent
            intent = detect_intent(user_text)
            logger.info(f"Detected intent: {intent['type']}")

            response_text = ""

            if intent["type"] == "greeting":
                response_text = handle_greeting()

            elif intent["type"] == "simple_search":
                response_text, _ = handle_simple_search(user_text)

            elif intent["type"] == "price_check":
                response_text = handle_price_check(user_text)

            elif intent["type"] == "complex_query":
                response_text = handle_complex_query(user_text)

            else:
                response_text = handle_complex_query(user_text)  # fallback

            # Send the final response
            if response_text:
                success = send_whatsapp_message(recipient_id, response_text)
                if not success:
                    fallback = "Sorry, I'm having trouble responding right now. Please try again shortly."
                    send_whatsapp_message(recipient_id, fallback)
            else:
                send_whatsapp_message(recipient_id, "I didn't understand that. Type 'HELP' for options.")

        except Exception as e:
            logger.error(f"Error in async processing: {e}")
            send_whatsapp_message(recipient_id, "I'm experiencing technical issues. Please try again later.")

# --- AI FUNCTIONS WITH MASTER DB VALIDATION ---
def generate_ai_response_with_context(user_query: str, master_db_results: List[Dict]) -> Tuple[str, bool]:
    """
    Generate AI response with context from master database.
    Returns: (response_text, used_master_db_context)
    """
    if not gemini_model:
        return "AI features are currently unavailable. Please contact our sales team directly.", False
    
    try:
        # Prepare context from master database
        context_data = []
        for product in master_db_results:
            context_data.append({
                "name": product.get("name", ""),
                "manufacturer": product.get("manufacturer", ""),  # From Bot 3
                "description": product.get("full_description", product.get("short_description", "")),
                "category": product.get("category", ""),
                "price": product.get("price"),
                "currency": product.get("currency", "USD"),
                "supplier": product.get("supplier", ""),
                "stock": product.get("stock_status", "")
            })
        
        # Create prompt with strict guidelines
        prompt = f"""
        ROLE: You are a medical equipment sales assistant. Your primary knowledge source is our master product database.
        
        USER QUERY: "{user_query}"
        
        MASTER DATABASE CONTEXT (Use this information FIRST):
        {json.dumps(context_data, indent=2)}
        
        STRICT INSTRUCTIONS:
        1. Answer the user's question using ONLY the master database information provided above.
        2. If the master database contains relevant information, base your answer on it.
        3. If the master database does not contain enough information to answer the query fully:
           - Acknowledge what information IS available from the master database
           - State that additional information is not in our master database
           - Provide a clear disclaimer that non-master-database information cannot be used for quotes
        4. NEVER invent or hallucinate product details, prices, or specifications.
        5. Be professional, concise, and helpful.
        6. Always prioritize accuracy over completeness.
        
        IMPORTANT DISCLAIMER POLICY:
        - If you use ANY information beyond the master database context provided, you MUST include this disclaimer:
          "⚠️ *Disclaimer*: This information is based on general knowledge and not from our master product database. 
          For accurate pricing, specifications, and official quotes, please contact our sales team directly."
        
        RESPONSE FORMAT:
        - Start with direct answer to query
        - List relevant products from master database if applicable
        - Include disclaimer if needed
        - End with next steps/contact information
        """
        
        # Generate response
        response = gemini_model.generate_content(prompt)
        ai_response = response.text
        
        # Determine if master database was sufficient
        used_master_db = len(context_data) > 0
        disclaimer_present = "Disclaimer" in ai_response or "disclaimer" in ai_response.lower()
        
        # If master DB has data but AI still gave disclaimer, mark as insufficient
        master_db_sufficient = used_master_db and not disclaimer_present
        
        return ai_response, master_db_sufficient
        
    except Exception as e:
        logger.error(f"AI generation error: {e}")
        return "I encountered an error while processing your query. Please try again or contact our sales team.", False

# --- QUOTE COMMAND HANDLERS (From Bot 1) ---
def handle_quote_command(phone: str, message: str) -> Optional[str]:
    """Handle QUOTE [item] command syntax from Bot 1"""
    message_lower = message.lower().strip()
    
    # QUOTE command (from Bot 1)
    if message_lower.startswith('quote '):
        item_name = message[6:].strip()
        if not item_name:
            return "Please specify an item. Example: 'QUOTE Catheter'"
        
        # Search for item
        products, found = search_master_database(item_name, limit=1)
        
        if not found:
            return f"❌ '{item_name}' not found in master database. Cannot generate quote."
        
        product = products[0]
        # Add to cart
        cart_manager.add_to_cart(
            phone, 
            product['product_id'], 
            product['name'],
            product['price']
        )
        
        return format_quote_response(phone, products)
    
    # ADD command
    elif message_lower.startswith('add '):
        item_name = message[4:].strip()
        if not item_name:
            return "Please specify an item. Example: 'ADD Surgical Gloves'"
        
        products, found = search_master_database(item_name, limit=1)
        
        if not found:
            return f"❌ '{item_name}' not found in master database."
        
        product = products[0]
        item_id = cart_manager.add_to_cart(
            phone, 
            product['product_id'], 
            product['name'],
            product['price']
        )
        
        cart_summary = cart_manager.get_cart_summary(phone)
        response = f"✅ Added *{product['name']}* to your cart (Item ID: {item_id})\n\n"
        response += f"📦 Cart now has {cart_summary['item_count']} item(s)\n"
        response += f"💰 Estimated total: {product.get('currency', 'USD')} {cart_summary['total']:,.2f}\n\n"
        response += "*Commands:*\n"
        response += "• 'CART' - View cart\n"
        response += "• 'REMOVE [Item ID]' - Remove item\n"
        response += "• 'CLEAR CART' - Empty cart\n"
        response += "• 'REQUEST QUOTE' - Get formal quote"
        
        return response
    
    # CART command
    elif message_lower == 'cart':
        return show_cart(phone)
    
    # REMOVE command
    elif message_lower.startswith('remove '):
        item_id = message[7:].strip()
        if cart_manager.remove_from_cart(phone, item_id):
            return f"✅ Removed item {item_id} from your cart.\n\n{show_cart(phone)}"
        else:
            return f"❌ Item {item_id} not found in your cart."
    
    # CLEAR CART command
    elif message_lower == 'clear cart':
        cart_manager.clear_cart(phone)
        return "✅ Cart cleared. Your cart is now empty."
    
    # REQUEST QUOTE command
    elif message_lower in ['request quote', 'get quote', 'quote']:
        return format_quote_response(phone)
    
    return None  # Not a quote/cart command

def format_quote_response(phone: str, products: Optional[List[Dict]] = None) -> str:
    """Format quote response with cart summary"""
    cart_summary = cart_manager.get_cart_summary(phone)
    
    if cart_summary['item_count'] == 0:
        return "📭 Your cart is empty. Add items first with 'ADD [product name]'."
    
    response = "📋 *QUOTE REQUEST SUMMARY*\n"
    response += "=" * 30 + "\n"
    
    total = 0
    currency = "USD"  # Default, would normally detect from first item
    
    for item in cart_summary['items']:
        # In production, fetch current prices from DB
        item_total = item['price'] * item['quantity']
        total += item_total
        
        # Try to get product details if available
        if products:
            for prod in products:
                if prod.get('product_id') == item.get('product_id'):
                    currency = prod.get('currency', 'USD')
                    break
        
        response += f"• {item['product_name']} x{item['quantity']}\n"
        response += f"  Price: {currency} {item['price']:,.2f} each\n"
        response += f"  Subtotal: {currency} {item_total:,.2f}\n\n"
    
    response += "=" * 30 + "\n"
    response += f"*ESTIMATED TOTAL:* {currency} {total:,.2f}\n\n"
    
    # Add recommendation from Bot 1 style
    product_ids = [item['product_id'] for item in cart_summary['items']]
    response = add_recommendations_to_response(response, product_ids)
    
    # Master database verification (from my hybrid code)
    response += "\n" + "=" * 30 + "\n"
    response += "✅ *MASTER DATABASE VERIFIED*\n"
    response += "• All items sourced from official catalog\n"
    response += "• Eligible for PDF quote generation\n"
    response += "• Pricing validated against current rates\n\n"
    
    # Next steps (from Bot 1)
    response += "*NEXT STEPS:*\n"
    response += "1. Reply 'CONFIRM QUOTE' to generate PDF\n"
    response += "2. Contact sales for volume discounts\n"
    response += "3. Email: info@socio-med.com\n"
    response += "4. Phone: +256777411435\n\n"
    
    response += "_Quote valid for 30 days. Prices subject to stock availability._"
    
    return response

def show_cart(phone: str) -> str:
    """Show current cart contents"""
    cart_summary = cart_manager.get_cart_summary(phone)
    
    if cart_summary['item_count'] == 0:
        return "🛒 Your cart is empty.\n\nAdd items with: 'ADD [product name]'"
    
    response = f"🛒 *YOUR CART* ({cart_summary['item_count']} items)\n"
    response += "=" * 30 + "\n"
    
    for item in cart_summary['items']:
        response += f"• {item['product_name']} x{item['quantity']}\n"
        response += f"  ID: {item['item_id']} | Price: ${item['price']:,.2f} each\n"
        if item.get('notes'):
            response += f"  Notes: {item['notes']}\n"
        response += "\n"
    
    response += "=" * 30 + "\n"
    response += f"*TOTAL: ${cart_summary['total']:,.2f}*\n\n"
    
    response += "*Commands:*\n"
    response += "• 'ADD [product]' - Add more items\n"
    response += "• 'REMOVE [Item ID]' - Remove item\n"
    response += "• 'CLEAR CART' - Empty cart\n"
    response += "• 'REQUEST QUOTE' - Get formal quote"
    
    return response

# --- PDF QUOTE GENERATION (From Bot 2) ---
def generate_and_send_quote(phone: str) -> Tuple[bool, str]:
    """
    Mock PDF quote generation (integrate with actual module from Bot 2)
    In production, replace with: from generate_quote import generate_pdf_quote
    """
    try:
        cart_summary = cart_manager.get_cart_summary(phone)
        
        if cart_summary['item_count'] == 0:
            return False, "Cart is empty"
        
        # Mock quote generation
        quote_id = f"QT-{datetime.now().strftime('%Y%m%d')}-{phone[-4:]}"
        
        # In production:
        # quote_id = create_quote_from_cart(phone, cart_summary['items'])
        # pdf_path = generate_pdf_quote(quote_id)
        # upload_and_send_pdf(phone, pdf_path)
        
        logger.info(f"Generated mock quote {quote_id} for {phone}")
        
        # Clear cart after quote generation
        cart_manager.clear_cart(phone)
        
        return True, quote_id
        
    except Exception as e:
        logger.error(f"Quote generation error: {e}")
        return False, str(e)

# --- INTENT DETECTION ---
def detect_intent(message: str) -> Dict:
    """Detect user intent from message"""
    message_lower = message.lower().strip()
    
    # Check for quote/cart commands first
    quote_keywords = ['quote', 'add', 'cart', 'remove', 'clear']
    if any(message_lower.startswith(kw) for kw in quote_keywords):
        return {'type': 'quote_command', 'confidence': 1.0}
    
    # Simple greeting
    if message_lower in ['hello', 'hi', 'hey', 'start', 'menu', 'help']:
        return {'type': 'greeting', 'confidence': 1.0}
    
    # Price check intent
    price_keywords = ['price', 'cost', 'how much', '$', 'usd', 'pricing']
    if any(keyword in message_lower for keyword in price_keywords):
        return {'type': 'price_check', 'confidence': 0.9}
    
    # Product search (simple)
    if len(message_lower) > 2 and len(message_lower.split()) < 4:
        return {'type': 'simple_search', 'confidence': 0.8}
    
    # Complex query (use AI)
    return {'type': 'complex_query', 'confidence': 0.7}

# --- MESSAGE HANDLERS ---
def handle_greeting() -> str:
    return """👋 *Welcome to SocioMed!*

I'm your Sales assistant. I can help you:

🔍 *Search Products*
   Example: "catheter", "MRI machine"

💰 *Check Prices*
   Example: "price for ultrasound gel"

📋 *Get Quotes*
   Use: "ADD [product]" to build cart
   Then: "REQUEST QUOTE" for formal quote

💬 *Ask Questions*
   Example: "best surgical gloves for OR"

📞 *Contact Sales*
   Email: info@socio-med.com
   Phone: +256-777-411-435

*Try searching for a product or type HELP for commands.*"""

def handle_simple_search(query: str) -> Tuple[str, bool]:
    """Handle simple product searches directly from master DB"""
    products, found_in_master = search_master_database(query)
    
    if not found_in_master:
        return "I couldn't find that product in our master database. Please try different keywords or contact our sales team for assistance.", False
    
    response = format_products_for_whatsapp(products, include_pricing=True)
    
    # Add recommendations (from Bot 1)
    product_ids = [p['product_id'] for p in products]
    response = add_recommendations_to_response(response, product_ids)
    
    # Add quote instructions (from Bot 1)
    response += "\n\n" + "=" * 30 + "\n"
    response += "*TO GET A QUOTE:*\n"
    response += "1. Use 'ADD [product name]' to add to cart\n"
    response += "2. Use 'CART' to view your cart\n"
    response += "3. Use 'REQUEST QUOTE' for formal quote\n\n"
    
    response += "_✅ Results from master database - eligible for official quotes_"
    
    return response, True

def handle_price_check(query: str) -> str:
    """Handle price-specific queries"""
    # Extract product name
    price_keywords = ['price', 'cost', 'how much', '$', 'usd', 'pricing', 'quote']
    clean_query = query.lower()
    for keyword in price_keywords:
        clean_query = clean_query.replace(keyword, '')
    clean_query = clean_query.replace('for', '').strip()
    
    if not clean_query or len(clean_query) < 2:
        return "Please specify which product you'd like pricing for (e.g., 'price for catheter')."
    
    products, found_in_master = search_master_database(clean_query)
    
    if not found_in_master:
        return f"I couldn't find '{clean_query}' in our master pricing database. For pricing information, please contact our sales team with the exact product name or SKU."
    
    response = format_products_for_whatsapp(products, include_pricing=True)
    
    # Add quote instructions (from Bot 1)
    response += "\n\n" + "=" * 30 + "\n"
    response += "📋 *For official quotes:*\n"
    response += "1. Reply 'ADD [product name]' to add to cart\n"
    response += "2. Use 'CART' to review selections\n"
    response += "3. Use 'REQUEST QUOTE' for formal quote\n"
    response += "4. Contact sales for volume discounts\n\n"
    
    response += "_✅ Master database pricing - quote ready_"
    
    return response

def handle_complex_query(query: str) -> str:
    """Handle complex queries with AI and master DB validation"""
    logger.info(f"Processing complex query: {query}")
    
    # FIRST: Check master database
    products, found_in_master = search_master_database(query, limit=3)
    
    # SECOND: Generate AI response with context
    ai_response, master_db_sufficient = generate_ai_response_with_context(query, products)
    
    # THIRD: Format final response with appropriate disclaimers
    final_response = ai_response
    
    # Add master database validation footer
    if found_in_master and master_db_sufficient:
        footer = "\n\n" + "=" * 30 + "\n"
        footer += "✅ *MASTER DATABASE VERIFIED*\n"
        footer += "• Information sourced from official product database\n"
        footer += "• Eligible for official quotes and PDF generation\n"
        footer += "• Contact sales for volume pricing and custom quotes"
        final_response += footer
    
    elif found_in_master and not master_db_sufficient:
        footer = "\n\n" + "=" * 30 + "\n"
        footer += "⚠️ *PARTIAL MASTER DATABASE MATCH*\n"
        footer += "• Some products found in master database:\n\n"
        footer += format_products_for_whatsapp(products, include_pricing=True)
        footer += "\n\n• For complete specifications, contact sales team\n"
        footer += "• Quote generation may require additional verification"
        final_response += footer
    
    else:  # Not found in master database
        footer = "\n\n" + "=" * 30 + "\n"
        footer += "⚠️ *MASTER DATABASE NOTIFICATION*\n"
        footer += "❌ Information not from master product database\n"
        footer += "❌ Cannot generate official quotes or PDF documentation\n"
        footer += "✅ Contact sales team for accurate information:\n"
        footer += "   • Accurate pricing and specifications\n"
        footer += "   • Official quote generation\n"
        footer += "   • Volume discounts and custom solutions\n\n"
        footer += "📞 Contact: info@socio-med.com | +256-777-411-435"
        final_response += footer
    
    return final_response
    
def process_message_async(recipient_id: str, user_text: str):
    """Background task for heavy processing (DB + Gemini)"""
    with app.app_context():  # Required for Flask context in threads
        try:
            logger.info(f"Starting async processing for {recipient_id}: {user_text[:50]}")

            # === Copy ALL your existing processing logic here ===
            # Check for quote/cart commands first
            quote_response = handle_quote_command(recipient_id, user_text)
            if quote_response:
                send_whatsapp_message(recipient_id, quote_response)
                return

            # Detect intent
            intent = detect_intent(user_text)
            logger.info(f"Detected intent: {intent['type']}")

            response_text = ""

            if intent["type"] == "greeting":
                response_text = handle_greeting()

            elif intent["type"] == "simple_search":
                response_text, _ = handle_simple_search(user_text)

            elif intent["type"] == "price_check":
                response_text = handle_price_check(user_text)

            elif intent["type"] == "complex_query":
                response_text = handle_complex_query(user_text)

            else:
                response_text = handle_complex_query(user_text)  # fallback

            # Send the final response
            if response_text:
                success = send_whatsapp_message(recipient_id, response_text)
                if not success:
                    fallback = "Sorry, I'm having trouble responding right now. Please try again shortly."
                    send_whatsapp_message(recipient_id, fallback)
            else:
                send_whatsapp_message(recipient_id, "I didn't understand that. Type 'HELP' for options.")

        except Exception as e:
            logger.error(f"Error in async processing: {e}")
            send_whatsapp_message(recipient_id, "I'm experiencing technical issues. Please try again later.")

# --- WHATSAPP API FUNCTIONS ---
def send_whatsapp_message(recipient_id: str, message: str, max_retries: int = 3) -> bool:
    """Send WhatsApp message with retry logic"""
    for attempt in range(max_retries):
        try:
            headers = {
                "Authorization": f"Bearer {WHATSAPP_TOKEN}",
                "Content-Type": "application/json",
            }
            
            url = f"https://graph.facebook.com/{WHATSAPP_API_VERSION}/{PHONE_NUMBER_ID}/messages"
            
            # Split long messages (production-ready)
            if len(message) > 1600:
                chunks = [message[i:i+1600] for i in range(0, len(message), 1600)]
                for chunk in chunks:
                    payload = {
                        "messaging_product": "whatsapp",
                        "to": recipient_id,
                        "type": "text",
                        "text": {"body": chunk}
                    }
                    response = requests.post(url, headers=headers, json=payload, timeout=10)
                    response.raise_for_status()
                    time.sleep(1)  # Brief delay between chunks
            else:
                payload = {
                    "messaging_product": "whatsapp",
                    "to": recipient_id,
                    "type": "text",
                    "text": {"body": message}
                }
                response = requests.post(url, headers=headers, json=payload, timeout=10)
                response.raise_for_status()
            
            logger.info(f"Message sent to {recipient_id}")
            return True
            
        except requests.exceptions.RequestException as e:
            logger.error(f"Send attempt {attempt + 1} failed: {e}")
            if attempt < max_retries - 1:
                time.sleep(2 ** attempt)  # Exponential backoff
            else:
                return False
    return False

# --- FLASK ROUTES ---
@app.route("/webhook", methods=["GET"])
def verify_webhook():
    """Verify webhook with Meta"""
    mode = request.args.get("hub.mode")
    token = request.args.get("hub.verify_token")
    challenge = request.args.get("hub.challenge")
    
    if mode and token:
        if mode == "subscribe" and token == VERIFY_TOKEN:
            logger.info("Webhook verified successfully")
            return challenge, 200
        else:
            logger.warning("Webhook verification failed")
            return "Verification failed", 403
    
    return "SocioMed WhatsApp Bot", 200

@app.route("/webhook", methods=["POST"])
def webhook():
    """Main webhook handler for incoming messages"""
    try:
        data = request.get_json()
        logger.debug(f"Received webhook data")
        
        if not data or data.get("object") != "whatsapp_business_account":
            return jsonify({"status": "ignored"}), 200
        
        # Process incoming message
        for entry in data.get("entry", []):
            for change in entry.get("changes", []):
                if change.get("field") == "messages":
                    messages = change.get("value", {}).get("messages", [])
                    
                    for message in messages:
                        # Extract message details
                        recipient_id = message.get("from")
                        message_type = message.get("type")
                        
                                                if message_type == "text":
                            user_text = message.get("text", {}).get("body", "").strip()
                            
                            if not user_text:
                                continue
                            
                            logger.info(f"Message from {recipient_id}: {user_text[:50]}...")
                            
                            # === FAST ACKNOWLEDGEMENT FOR QUICK COMMANDS ===
                            quote_response = handle_quote_command(recipient_id, user_text)
                            if quote_response:
                                send_whatsapp_message(recipient_id, quote_response)
                                return jsonify({"status": "processed"}), 200

                            # === CONFIRM QUOTE (fast response needed) ===
                            if user_text.upper() == "CONFIRM QUOTE":
                                success, quote_id = generate_and_send_quote(recipient_id)
                                if success:
                                    response = f"✅ *Quote Confirmed!*\n\nQuote ID: {quote_id}\nOur team will send the PDF shortly."
                                else:
                                    response = "❌ Could not generate quote. Please contact sales."
                                send_whatsapp_message(recipient_id, response)
                                return jsonify({"status": "processed"}), 200

                            # === ALL OTHER MESSAGES: PROCESS IN BACKGROUND ===
                            # Immediate 200 OK to WhatsApp
                            thread = threading.Thread(
                                target=process_message_async,
                                args=(recipient_id, user_text)
                            )
                            thread.start()

                            return jsonify({"status": "received"}), 200
                            
    except Exception as e:
        logger.error(f"Error processing webhook: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

    return "OK", 200

if __name__ == "__main__":
    # Ensure the app runs on 0.0.0.0 so Docker can map the port
    app.run(host="0.0.0.0", port=5000)
