import os
import pandas as pd
import glob
import re
import logging
import shutil
from datetime import datetime
from sqlalchemy import create_engine, text

# --- CONFIGURATION ---
class Config:
    DB_USER = os.getenv('POSTGRES_USER', 'postgres')
    DB_PASSWORD = os.getenv('POSTGRES_PASSWORD')
    if not DB_PASSWORD:
        raise ValueError("POSTGRES_PASSWORD is required.")
    DB_HOST = os.getenv('DATABASE_HOST', 'sociomed-database')
    DB_PORT = os.getenv('POSTGRES_PORT', '5432')
    DB_NAME = os.getenv('POSTGRES_DB', 'sociomed_db')
    
    DATABASE_URL = f"postgresql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"
    
    # Path inside Docker container (mapped to ./data in docker-compose)
    BASE_DIR = "/app/data"
    PROCESSED_DIR = os.path.join(BASE_DIR, "processed")
    FAILED_DIR = os.path.join(BASE_DIR, "failed")

    # --- HEADER STANDARDIZATION MAP ---
    # format: "staging_table_name": {"CSV Header": "db_column_name"}
    HEADER_MAP = {
        # 1. Main Product Database (Source: sociomed_db - db_4_g.csv)
        "stg_db_4_g": {
            "Product Category": "category",
            "Product_ID": "sku",
            "Product Name": "name",
            "Variant": "variant",
            "Size": "size_spec",
            "Price": "price",
            "Inventory Status": "stock_status",
            "Min_Order_Qty": "min_order_quantity",
            "Lead_Time_Days": "lead_time_days",
            "Product_Line": "brand",
            "Product_Description": "description",
            "Regulatory_Status": "regulatory_status",
            "Manufacturer": "manufacturer",
            "Distributor": "distributor_name", # Note: Schema might need update to handle distributor if not present
            "Code_Straight": "code_straight",
            "Code_Curve": "code_curve"
        },

        # 2. Bundles & Kits (Source: sociomed_db - bund_kits.csv)
        "stg_bund_kits": {
            "Kit_Name": "name",
            "Bundle_Contents": "description",
            "Component_Total_UGX": "total_price", 
            # Note: Using component total as bundle price for now
            "Kit_ID": "kit_id",
            "Component_Product_ID": "component_sku",
            "Component_Name": "component_name",
            "Quantity": "quantity",
            "Component_Unit_Price_UGX": "unit_price",
            "Discount_Percentage": "discount_percentage"
        },

        # 3. Manufacturers & Distributors (Source: sociomed_db - man&_dis.csv)
        "stg_man_and_dis": {
            "Name": "name",
            "License Number": "license_number",  # Store in api_details or notes
            "Contact": "contact_phone",
            "Address": "address", # Mapping Address to address field
            "Column 1": "sector",   # e.g. Human, Medical Devices
            "Premise Type": "premise_type",
            "District": "district",
            "Region": "region"
        },

        # 4. Supply Contacts (Source: sociomed_db - supply_contacts.csv)
        "stg_supply_contacts": {
            "Company_Name": "name", 
            "Email": "contact_email",
            "Website": "website",
            "Phone": "contact_phone",
            "Entity_Type": "entity_type",
            "Contact_Person": "contact_person",
            "Address": "address",
            "Primary_Products": "primary_products",
            "Payment_Terms": "payment_terms",
            "MOQ": "moq",
            "Lead_Time_Days": "lead_time_days"
        },

        # 5. Premises/Clients (Source: sociomed_db - premises.csv)
        "stg_premises": {
            "Premise Name": "clinic_name",
            "Contact Person": "contact_person",
            "Phone Number": "phone_number",
            "Physical Address": "address",
            "Email": "email",
            "TPIN": "tax_id",
            "Premise No": "premise_no",
            "Type": "premise_type",
            "Street": "street",
            "PSU No": "psu_no",
            "Category": "category",
            "District": "district",
            "Region": "region"
        },
        
        # 6. Katsan Products (Source: sociomed_db - katsan_pdts.csv)
        "stg_katsan_pdts": {
            "Product_Code_SKU": "sku",
            "Product_Name": "name",
            "Description": "description",
            "Category": "category",
            "Brand": "brand",
            "Supplier": "supplier_name",
            "USP_Size": "usp_size",
            "Needle_Type": "needle_type",
            "Needle_Length": "needle_length",
            "Suture_Length": "suture_length",
            "Color": "color"
        },

        # 7. Price Comparison (Source: sociomed_db - price_comp.csv)
        "stg_price_comp": {
            "Product_Type": "product_type",
            "St_Stone_Price_UGX": "st_stone_price_ugx",
            "Competitor_Avg_UGX": "competitor_avg_ugx",
            "Price_Difference_Percentage": "price_diff_percent",
            "Market_Position": "market_position",
            "Volume_Discount_Available": "volume_discount_available"
        },

        # 8. Reorder Levels (Source: sociomed_db - reorder.csv)
        "stg_reorder": {
            "Product_ID": "sku",
            "Product_Name": "name",
            "Current_Stock": "current_stock",
            "Min_Stock_Level": "min_stock_level",
            "Reorder_Qty": "reorder_qty",
            "Last_Order_Date": "last_order_date",
            "Next_Order_Date": "next_order_date",
            "Supplier": "supplier_name",
            "Estimated_Delivery": "estimated_delivery"
        },

        # 9. Product Recommendations (Source: sociomed_db - prdt_reco.csv)
        "stg_prdt_reco": {
            "Suggested_Product": "suggested_product",
            "Target_Market": "target_market",
            "Estimated_Price_UGX": "estimated_price_ugx",
            "Development_Status": "development_status",
            "Expected_Launch": "expected_launch",
            "Competitive_Advantage": "competitive_advantage"
        },

        # 10. Product Categories Metrics (Source: sociomed_db - prdt_cat.csv)
        "stg_prdt_cat": {
            "Product Category": "category",
            "Product_Count": "product_count",
            "Inventory_Items": "inventory_items",
            "Non_Inventory_Items": "non_inventory_items",
            "Average_Price_UGX": "average_price_ugx",
            "Top_Selling_Product": "top_selling_product",
            "Reorder_Level": "reorder_level"
        }
    }

# --- LOGGING SETUP ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s', handlers=[logging.StreamHandler()])
logger = logging.getLogger(__name__)

class SocioMedETL:
    def __init__(self):
        self.engine = self._connect_db()
        self._setup_directories()

    def _connect_db(self):
        try:
            return create_engine(Config.DATABASE_URL)
        except Exception as e:
            logger.critical(f"❌ Database connection failed: {e}")
            raise

    def _setup_directories(self):
        os.makedirs(Config.PROCESSED_DIR, exist_ok=True)
        os.makedirs(Config.FAILED_DIR, exist_ok=True)

    def clean_name(self, name):
        s = str(name).strip().lower()
        s = s.replace('&', '_and_').replace(' ', '_').replace('-', '_')
        s = re.sub(r'[^\w_]', '', s)
        return s.lstrip('_')

    def move_file(self, filepath, destination_dir):
        filename = os.path.basename(filepath)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        new_name = f"{timestamp}_{filename}"
        dest_path = os.path.join(destination_dir, new_name)
        shutil.move(filepath, dest_path)
        return dest_path

    def load_staging(self, filepath):
        filename = os.path.basename(filepath)
        # Handle "sociomed_db - name.csv" format
        raw_name = filename.split('.')[0].replace('sociomed_db - ', '').replace('sociomed_db', '').strip()
        clean_filename = self.clean_name(raw_name)
        table_name = f"stg_{clean_filename}"

        # 1. Read File
        if filename.lower().endswith('.csv'):
            encodings = ['utf-8', 'latin1', 'cp1252']
            df = None
            for enc in encodings:
                try:
                    df = pd.read_csv(filepath, encoding=enc, on_bad_lines='skip')
                    break
                except UnicodeDecodeError:
                    continue
            if df is None: raise ValueError(f"Could not decode {filename}")
        else:
            try:
                df = pd.read_excel(filepath)
            except Exception as e:
                # Fallback if openpyxl is missing or file corrupt
                logger.error(f"Excel read failed: {e}")
                raise

        # 2. Apply Header Map
        if table_name in Config.HEADER_MAP:
            mapping = Config.HEADER_MAP[table_name]
            logger.info(f"   Using header map for {table_name}")
            df.rename(columns=mapping, inplace=True)

        # 3. Clean Headers & Load
        df.columns = [self.clean_name(col) for col in df.columns]
        df.dropna(how='all', inplace=True)

        logger.info(f"   -> Loading to staging table: '{table_name}' ({len(df)} rows)")
        df.to_sql(table_name, self.engine, if_exists='replace', index=False)
        return table_name

    def transform_to_schema(self):
        logger.info("⚙️  Running Transformations (Staging -> Production)...")
        with self.engine.begin() as conn:
            
            # 1. SUPPLIERS (from stg_man_and_dis)
            if self._table_exists(conn, 'stg_man_and_dis'):
                logger.info("   -> Transforming Suppliers...")
                conn.execute(text("""
                    INSERT INTO suppliers (name, type, contact_phone)
                    SELECT DISTINCT name, 'PARTNER', contact_phone
                    FROM stg_man_and_dis
                    ON CONFLICT (supplier_id) DO NOTHING;
                """))

            # 2. PRODUCTS (from stg_db_4_g) -> This is the REAL catalog
            if self._table_exists(conn, 'stg_db_4_g'):
                logger.info("   -> Transforming Products (Main DB)...")
                conn.execute(text("""
                    INSERT INTO products (sku, name, category, description, brand, manufacturer, regulatory_status)
                    SELECT DISTINCT 
                        sku, 
                        name, 
                        category, 
                        description,
                        brand,
                        manufacturer,
                        regulatory_status
                    FROM stg_db_4_g
                    WHERE sku IS NOT NULL
                    ON CONFLICT (sku) DO UPDATE SET 
                        category = EXCLUDED.category,
                        name = EXCLUDED.name,
                        description = EXCLUDED.description;
                """))
                
                # 2b. OFFERINGS (from stg_db_4_g) -> Populate Prices/Inventory
                # We link these to SocioMed (Supplier ID 1) as default
                logger.info("   -> Transforming Product Offerings...")
                conn.execute(text("""
                    INSERT INTO product_offerings (product_id, supplier_id, price, stock_status, min_order_quantity, lead_time_days)
                    SELECT 
                        p.product_id,
                        1, -- Defaulting to Supplier 1 (SocioMed)
                        CAST(REGEXP_REPLACE(stg.price::text, '[^0-9.]', '', 'g') AS DECIMAL),
                        stg.stock_status,
                        CAST(NULLIF(stg.min_order_quantity, '') AS INTEGER),
                        CAST(NULLIF(stg.lead_time_days, '') AS INTEGER)
                    FROM stg_db_4_g stg
                    JOIN products p ON stg.sku = p.sku
                    WHERE stg.price IS NOT NULL
                    ON CONFLICT (product_id, supplier_id) DO UPDATE SET
                        price = EXCLUDED.price,
                        stock_status = EXCLUDED.stock_status;
                """))

            # 3. KATSAN PRODUCTS (Enriching Catalog)
            if self._table_exists(conn, 'stg_katsan_pdts'):
                logger.info("   -> Transforming Katsan Products...")
                conn.execute(text("""
                    INSERT INTO products (sku, name, category, description, brand)
                    SELECT DISTINCT 
                        sku, name, category, description, brand
                    FROM stg_katsan_pdts
                    WHERE sku IS NOT NULL
                    ON CONFLICT (sku) DO NOTHING;
                """))

            # 4. BUNDLES (from stg_bund_kits)
            if self._table_exists(conn, 'stg_bund_kits'):
                logger.info("   -> Transforming Bundles...")
                conn.execute(text("""
                    INSERT INTO bundles (name, description, total_price, currency)
                    SELECT DISTINCT 
                        name, description, 
                        CAST(REGEXP_REPLACE(total_price::text, '[^0-9.]', '', 'g') AS DECIMAL),
                        'UGX'
                    FROM stg_bund_kits
                    WHERE name IS NOT NULL
                    ON CONFLICT (bundle_id) DO NOTHING;
                """))

            # 5. CLIENTS/PREMISES
            if self._table_exists(conn, 'stg_premises'):
                logger.info("   -> Transforming Clients (Premises)...")
                conn.execute(text("""
                    INSERT INTO users (phone_number, clinic_name, contact_person, email, tax_id, address)
                    SELECT DISTINCT 
                        COALESCE(phone_number, 'UNK-' || MD5(clinic_name)), 
                        clinic_name, 
                        contact_person, 
                        email, 
                        tax_id, 
                        address
                    FROM stg_premises
                    WHERE clinic_name IS NOT NULL
                    ON CONFLICT (phone_number) DO NOTHING;
                """))

        logger.info("✅ Transformations Complete.")

    def _table_exists(self, conn, table_name):
        return conn.execute(text(f"SELECT to_regclass('{table_name}')")).scalar() is not None

    def run(self):
        logger.info(f"🚀 Starting ETL Job. Watching: {Config.BASE_DIR}")
        
        files = []
        for ext in ["*.csv", "*.CSV", "*.xlsx", "*.XLSX", "*.xls"]:
            files.extend(glob.glob(os.path.join(Config.BASE_DIR, ext)))

        if not files:
            logger.warning("⚠️  No data files found. Is the volume mounted correctly?")
            return

        success_count = 0
        for filepath in files:
            try:
                self.load_staging(filepath)
                self.move_file(filepath, Config.PROCESSED_DIR)
                success_count += 1
            except Exception as e:
                logger.error(f"   ❌ FAILED {os.path.basename(filepath)}: {e}")
                self.move_file(filepath, Config.FAILED_DIR)

        if success_count > 0:
            try:
                self.transform_to_schema()
            except Exception as e:
                logger.error(f"❌ Transformation Phase Failed: {e}")

if __name__ == "__main__":
    SocioMedETL().run()
