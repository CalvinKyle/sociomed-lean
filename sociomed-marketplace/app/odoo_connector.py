import xmlrpc.client
import os
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class OdooConnector:
    def __init__(self):
        self.url = os.getenv("ODOO_URL")
        self.db = os.getenv("ODOO_DB")
        self.username = os.getenv("ODOO_USER")
        self.password = os.getenv("ODOO_PASSWORD")
        self.common = xmlrpc.client.ServerProxy(f'{self.url}/xmlrpc/2/common')
        self.uid = self.common.authenticate(self.db, self.username, self.password, {})
        self.models = xmlrpc.client.ServerProxy(f'{self.url}/xmlrpc/2/object')

    def search_product_templates(self, query, limit=5):
        """
        Searches for the 'Parent' templates (e.g., 'CVC Catheter').
        Returns list of attributes available (e.g., Sizes: 10Fr, 12Fr).
        """
        domain = [
            '|',
            ('name', 'ilike', query),
            ('description_sale', 'ilike', query),
            ('sale_ok', '=', True)
        ]
        
        # Search 'product.template' (The Parent), not 'product.product' (The Variant)
        # We fetch 'attribute_line_ids' to see what options exist
        fields = ['name', 'list_price', 'attribute_line_ids', 'qty_available']
        
        template_ids = self.models.execute_kw(self.db, self.uid, self.password,
            'product.template', 'search', [domain], {'limit': limit})
        
        templates = self.models.execute_kw(self.db, self.uid, self.password,
            'product.template', 'read', [template_ids], {'fields': fields})
            
        results = []
        for t in templates:
            # Fetch the actual attribute names and values
            attributes = {}
            if t['attribute_line_ids']:
                lines = self.models.execute_kw(self.db, self.uid, self.password,
                    'product.template.attribute.line', 'read', [t['attribute_line_ids']], 
                    {'fields': ['display_name', 'value_ids']})
                
                for line in lines:
                    # Parse "Size: 10Fr, 12Fr"
                    attr_name = line['display_name'].split(':')[0]
                    # Fetch value names
                    val_ids = line['value_ids']
                    values = self.models.execute_kw(self.db, self.uid, self.password,
                        'product.attribute.value', 'read', [val_ids], {'fields': ['name']})
                    attributes[attr_name] = [v['name'] for v in values]

            results.append({
                'template_id': t['id'],
                'name': t['name'],
                'price': t['list_price'],
                'attributes': attributes, # e.g. {'Size': ['10Fr', '12Fr']}
                'stock': t['qty_available']
            })
            
        return results

    def get_variant_id(self, template_id, selected_attributes):
        """
        Finds the specific Variant ID based on user selection.
        selected_attributes = {'Size': '10Fr', 'Lumen': 'Double'}
        """
        # Logic to find the specific product.product ID matching these attributes
        # This requires searching 'product.product' where 'product_tmpl_id' matches
        # AND all attribute values match.
        # (Simplified for brevity - in production, you iterate through variants)
        domain = [('product_tmpl_id', '=', template_id)]
        variants = self.models.execute_kw(self.db, self.uid, self.password,
            'product.product', 'search_read', [domain], 
            {'fields': ['product_template_attribute_value_ids']})
            
        # Match logic would go here
        # Return the specific product_id (e.g., 452)
        return variants[0]['id'] # Placeholder
        
    def search_products(self, query, limit=5):
        """
        Finds products and identifies if they are Dropship or Own Inventory.
        """
        domain = [
            '|', '|',
            ('name', 'ilike', query),
            ('default_code', 'ilike', query),  # SKU match
            ('description_sale', 'ilike', query),
            ('sale_ok', '=', True)
        ]
        
        # Fetch fields including 'accessory_product_ids' for recommendations
        fields = ['name', 'default_code', 'list_price', 'qty_available', 
                  'uom_id', 'seller_ids', 'accessory_product_ids', 'alternative_product_ids']
        
        product_ids = self.models.execute_kw(self.db, self.uid, self.password,
            'product.product', 'search', [domain], {'limit': limit})
        
        products = self.models.execute_kw(self.db, self.uid, self.password,
            'product.product', 'read', [product_ids], {'fields': fields})
            
        results = []
        for p in products:
            # Business Logic: Inventory Source
            stock = p['qty_available']
            is_dropship = stock <= 0 and p['seller_ids']
            
            availability = "In Stock" if stock > 0 else ("Available via Partner" if is_dropship else "Out of Stock")
            
            results.append({
                'id': p['id'],
                'name': p['name'],
                'sku': p['default_code'],
                'price': p['list_price'],
                'availability': availability,
                'has_accessories': bool(p['accessory_product_ids']), # Flag for the bot to check
                'has_alternatives': bool(p['alternative_product_ids'])
            })
        return results

    def get_product_recommendations(self, product_id):
        """
        Fetches Cross-sells (Reagents/Consumables) and Upsells (Substitutes).
        """
        product = self.models.execute_kw(self.db, self.uid, self.password,
            'product.product', 'read', [product_id], 
            {'fields': ['accessory_product_ids', 'alternative_product_ids']})[0]
            
        recs = {'consumables': [], 'substitutes': []}
        
        # Fetch details for Accessories (Consumables)
        if product['accessory_product_ids']:
            acc_ids = product['accessory_product_ids']
            acc_details = self.models.execute_kw(self.db, self.uid, self.password,
                'product.product', 'read', [acc_ids], {'fields': ['name', 'list_price']})
            recs['consumables'] = acc_details

        # Fetch details for Alternatives (Substitutes)
        if product['alternative_product_ids']:
            alt_ids = product['alternative_product_ids']
            alt_details = self.models.execute_kw(self.db, self.uid, self.password,
                'product.product', 'read', [alt_ids], {'fields': ['name', 'list_price']})
            recs['substitutes'] = alt_details
            
        return recs

    def create_quotation(self, customer_phone, line_items):
        """
        Creates a formal Quote in Odoo for the customer. If item is a 'Kit' (Bundle), Odoo automatically expands it on the Delivery Slip,
        but keeps it as one line on the Quote (Sales Order).
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
