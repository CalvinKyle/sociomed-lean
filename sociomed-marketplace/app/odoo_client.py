import xmlrpc.client
import logging
from typing import List, Dict, Optional
from functools import lru_cache
import hashlib
import json

logger = logging.getLogger(__name__)

class OdooClient:
    def __init__(self):
        self.url = os.getenv('ODOO_URL', 'https://your-odoo.com')
        self.db = os.getenv('ODOO_DB', 'sociomed')
        self.username = os.getenv('ODOO_USERNAME')
        self.api_key = os.getenv('ODOO_API_KEY')
        
        if not all([self.url, self.db, self.username, self.api_key]):
            raise ValueError("Odoo credentials not configured")
        
        # Authenticate
        common = xmlrpc.client.ServerProxy(f'{self.url}/xmlrpc/2/common')
        self.uid = common.authenticate(self.db, self.username, self.api_key, {})
        
        if not self.uid:
            raise ConnectionError("Odoo authentication failed")
        
        self.models = xmlrpc.client.ServerProxy(f'{self.url}/xmlrpc/2/object')
        logger.info(f"Connected to Odoo as user {self.uid}")
    
    def _execute(self, model: str, method: str, *args, **kwargs):
        """Execute Odoo API call with error handling"""
        try:
            return self.models.execute_kw(
                self.db, self.uid, self.api_key,
                model, method, args, kwargs
            )
        except Exception as e:
            logger.error(f"Odoo API error: {e}")
            raise
    
    @lru_cache(maxsize=1000)
    def search_products(self, query: str, limit: int = 10) -> List[Dict]:
        """
        Search products in Odoo using their built-in search
        
        Odoo search uses domain filters: [('field', 'operator', 'value')]
        """
        domain = [
            '|', '|', '|',
            ('name', 'ilike', query),
            ('default_code', 'ilike', query),  # SKU
            ('description_sale', 'ilike', query),
            ('categ_id.name', 'ilike', query)
        ]
        
        fields = [
            'id', 'name', 'default_code', 'list_price', 
            'standard_price', 'qty_available', 'categ_id',
            'description_sale', 'uom_name', 'image_128'
        ]
        
        product_ids = self._execute(
            'product.product', 'search', 
            domain, {'limit': limit}
        )
        
        if not product_ids:
            return []
        
        products = self._execute(
            'product.product', 'read',
            product_ids, fields
        )
        
        # Transform to your format
        return [self._format_product(p) for p in products]
    
    def _format_product(self, odoo_product: Dict) -> Dict:
        """Convert Odoo product to WhatsApp-friendly format"""
        return {
            "product_id": odoo_product['id'],
            "name": odoo_product['name'],
            "sku": odoo_product.get('default_code', 'N/A'),
            "price": odoo_product.get('list_price', 0),
            "currency": "UGX",  # Get from company settings
            "stock_qty": int(odoo_product.get('qty_available', 0)),
            "availability": "IN_STOCK" if odoo_product.get('qty_available', 0) > 0 else "ORDER_ON_DEMAND",
            "category": odoo_product.get('categ_id', [False, 'Uncategorized'])[1],
            "description": odoo_product.get('description_sale', ''),
            "lead_time": 7  # Default, or get from supplier info
        }
    
    def get_product_by_id(self, product_id: int) -> Optional[Dict]:
        """Get single product details"""
        try:
            products = self._execute(
                'product.product', 'read',
                [product_id],
                ['id', 'name', 'default_code', 'list_price', 'qty_available']
            )
            return self._format_product(products[0]) if products else None
        except Exception as e:
            logger.error(f"Failed to fetch product {product_id}: {e}")
            return None
    
    def create_sale_order(self, customer_phone: str, cart_items: List[Dict]) -> int:
        """
        Create sale order in Odoo from WhatsApp cart
        
        Returns: sale_order_id
        """
        # 1. Get or create customer (partner)
        partner_id = self._get_or_create_partner(customer_phone)
        
        # 2. Build order lines
        order_lines = []
        for item in cart_items:
            order_lines.append((0, 0, {
                'product_id': item['product_id'],
                'product_uom_qty': item['quantity'],
                'price_unit': item['price']
            }))
        
        # 3. Create sale order
        order_vals = {
            'partner_id': partner_id,
            'order_line': order_lines,
            'note': f'Created via WhatsApp Bot from {customer_phone}',
            'origin': 'WhatsApp'
        }
        
        order_id = self._execute(
            'sale.order', 'create', order_vals
        )
        
        logger.info(f"Created Odoo sale order {order_id} for {customer_phone}")
        return order_id
    
    def _get_or_create_partner(self, phone: str) -> int:
        """Get existing customer or create new one"""
        # Search by phone
        partner_ids = self._execute(
            'res.partner', 'search',
            [('phone', '=', phone)],
            {'limit': 1}
        )
        
        if partner_ids:
            return partner_ids[0]
        
        # Create new partner
        partner_id = self._execute(
            'res.partner', 'create',
            {
                'name': f'WhatsApp Customer {phone}',
                'phone': phone,
                'customer_rank': 1,
                'comment': 'Created via WhatsApp Bot'
            }
        )
        
        # Store mapping in PostgreSQL
        with engine.begin() as conn:
            conn.execute(text("""
                UPDATE users 
                SET odoo_partner_id = :pid 
                WHERE phone_number = :phone
            """), {"pid": partner_id, "phone": phone})
        
        return partner_id
    
    def get_product_stock(self, product_id: int) -> Dict:
        """Get real-time stock levels"""
        stock = self._execute(
            'product.product', 'read',
            [product_id],
            ['qty_available', 'virtual_available', 'outgoing_qty']
        )
        
        return {
            "on_hand": stock[0]['qty_available'],
            "available": stock[0]['virtual_available'],
            "reserved": stock[0]['outgoing_qty']
        }
    
    def update_stock_from_odoo(self):
        """
        Sync Odoo inventory → PostgreSQL cache
        (Run this periodically or via Odoo webhook)
        """
        # Get all products with stock changes in last hour
        products = self._execute(
            'product.product', 'search_read',
            [('write_date', '>', '2024-01-01')],  # Use dynamic date
            ['id', 'name', 'qty_available']
        )
        
        # Update cache
        with engine.begin() as conn:
            for product in products:
                conn.execute(text("""
                    INSERT INTO search_cache (query_hash, query_text, results, expires_at)
                    VALUES (:hash, :query, :results, NOW() + INTERVAL '1 hour')
                    ON CONFLICT (query_hash) DO UPDATE
                    SET results = EXCLUDED.results, expires_at = EXCLUDED.expires_at
                """), {
                    "hash": hashlib.md5(f"product_{product['id']}".encode()).hexdigest(),
                    "query": product['name'],
                    "results": json.dumps([self._format_product(product)])
                })

# Initialize
odoo_client = OdooClient()
