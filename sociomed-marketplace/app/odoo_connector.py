import xmlrpc.client
import os
import logging

# Configure logging to track errors
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class OdooConnector:
    def __init__(self):
        # Load credentials from environment variables
        self.url = os.getenv("ODOO_URL")
        self.db = os.getenv("ODOO_DB")
        self.username = os.getenv("ODOO_USER")
        self.password = os.getenv("ODOO_PASSWORD")
        
        try:
            # Connect to Odoo
            self.common = xmlrpc.client.ServerProxy('{}/xmlrpc/2/common'.format(self.url))
            self.uid = self.common.authenticate(self.db, self.username, self.password, {})
            self.models = xmlrpc.client.ServerProxy('{}/xmlrpc/2/object'.format(self.url))
            logger.info("✅ Connected to Odoo ERP successfully.")
        except Exception as e:
            logger.error(f"❌ Failed to connect to Odoo: {e}")
            raise

    def search_products(self, query, limit=7):
        """
        Search for products in Odoo.
        Smart Logic: Distinguishes between 'In Stock' and 'Partner Stock'.
        """
        # Search for items that look like the query AND are sellable
        domain = [
            '|', 
            ('name', 'ilike', query), 
            ('default_code', 'ilike', query), # Searches SKU
            ('sale_ok', '=', True),           # Must be a sellable item
            ('is_published', '=', True)       # Must be published on website
        ]
        
        # 1. Find Product IDs
        product_ids = self.models.execute_kw(self.db, self.uid, self.password,
            'product.product', 'search', [domain], {'limit': limit})
        
        if not product_ids:
            return []

        # 2. Get Details (Price, Stock, and Vendor Info)
        fields = ['name', 'default_code', 'list_price', 'qty_available', 
                  'uom_id', 'description_sale', 'seller_ids']
        
        products = self.models.execute_kw(self.db, self.uid, self.password,
            'product.product', 'read', [product_ids], {'fields': fields})
            
        formatted_products = []
        for p in products:
            # LOGIC: If we have 0 stock, but a Vendor is listed, it's a Partner Item.
            stock = p['qty_available']
            is_partner_stock = stock <= 0 and p['seller_ids']
            
            availability_label = ""
            if stock > 0:
                availability_label = f"In Stock: {int(stock)}"
            elif is_partner_stock:
                availability_label = "✅ Available (Direct from Partner)" 
            else:
                availability_label = "Out of Stock"

            formatted_products.append({
                'product_id': p['id'],
                'name': p['name'],
                'price': p['list_price'],
                'currency': 'UGX', 
                'availability': availability_label,
                'manufacturer': p.get('default_code', 'Generic'), 
                'description': p.get('description_sale', '') or p['name']
            })
            
        return formatted_products

    def create_quotation(self, customer_phone, line_items):
        """
        Creates a formal Quote in Odoo for the customer.
        """
        # 1. Find or Create Customer by Phone
        partner_ids = self.models.execute_kw(self.db, self.uid, self.password,
            'res.partner', 'search', [[('phone', '=', customer_phone)]])
        
        if partner_ids:
            partner_id = partner_ids[0]
        else:
            partner_id = self.models.execute_kw(self.db, self.uid, self.password,
                'res.partner', 'create', [{
                    'name': f"WhatsApp Customer {customer_phone}", 
                    'phone': customer_phone
                }])

        # 2. Prepare Order Lines
        order_lines = []
        for item in line_items:
            order_lines.append((0, 0, {
                'product_id': int(item['product_id']),
                'product_uom_qty': item['qty'],
            }))

        # 3. Create the Order
        order_id = self.models.execute_kw(self.db, self.uid, self.password,
            'sale.order', 'create', [{
                'partner_id': partner_id,
                'order_line': order_lines,
                'origin': 'WhatsApp Bot',
                'client_order_ref': f"WA-{customer_phone[-4:]}"
            }])
            
        # 4. Return the Quote Number (e.g., S00012)
        order_name = self.models.execute_kw(self.db, self.uid, self.password,
            'sale.order', 'read', [order_id], {'fields': ['name']})[0]['name']
            
        return order_name
