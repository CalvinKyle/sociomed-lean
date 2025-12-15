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
    DB_USER = os.getenv('POSTGRES_USER', 'sociomed_user')
    DB_PASSWORD = os.getenv('POSTGRES_PASSWORD', 'secure_password_here') # Update with actual default if needed
    DB_HOST = os.getenv('DATABASE_HOST', 'sociomed-database')
    DB_PORT = os.getenv('POSTGRES_PORT', '5432')
    DB_NAME = os.getenv('POSTGRES_DB', 'sociomed')
    
    DATABASE_URL = f"postgresql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"
    
    BASE_DIR = "/data/excel"
    PROCESSED_DIR = os.path.join(BASE_DIR, "processed")
    FAILED_DIR = os.path.join(BASE_DIR, "failed")

    # Header mappings match the provided CSV structure
    HEADER_MAP = {
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
            "Distributor": "distributor_name"
        },
        "stg_bund_kits": {
            "Kit_Name": "name",
            "Kit_ID": "kit_code",
            "Component_Product_ID": "component_sku",
            "Component_Name": "component_name",
            "Quantity": "quantity",
            "Component_Unit_Price_UGX": "unit_price",
            "Discount_Percentage": "discount_percent"
        },
        "stg_supply_contacts": {
            "Company_Name": "name", 
            "Email": "contact_email",
            "Phone": "contact_phone",
            "Entity_Type": "business_type",
            "Address": "address_line1",
            "Lead_Time_Days": "lead_time_days"
        },
        "stg_premises": {
            "Premise Name": "organization_name",
            "Physical Address": "address",
            "Premise No": "premise_no",
            "Type": "organization_type",
            "District": "district",
            "Region": "region",
            "Contact Person": "contact_person_name",
            "Phone Number": "phone_number"
        },
         "stg_katsan_pdts": {
            "Product_Code_SKU": "sku",
            "Product_Name": "name",
            "Description": "description",
            "Category": "category",
            "Brand": "brand",
            "Supplier": "supplier_name"
        }
    }

# --- LOGGING SETUP ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
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
        """Sanitizes column names for SQL."""
        s = str(name).strip().lower()
        s = s.replace('&', '_and_').replace(' ', '_').replace('-', '_').replace('/', '_')
        s = re.sub(r'[^\w_]', '', s)
        return s.lstrip('_')

    def load_staging(self, filepath):
        """Reads Excel/CSV and dumps into staging tables."""
        filename = os.path.basename(filepath)
        # Handle "sociomed_db - name.csv" format logic
        raw_name = filename.split('.')[0]
        if ' - ' in raw_name:
            raw_name = raw_name.split(' - ')[-1]
        
        clean_filename = self.clean_name(raw_name)
        table_name = f"stg_{clean_filename}"

        logger.info(f"📂 Processing {filename} -> {table_name}")

        try:
            if filename.lower().endswith('.csv'):
                # Try multiple encodings for resilience
                try:
                    df = pd.read_csv(filepath, encoding='utf-8', on_bad_lines='skip')
                except UnicodeDecodeError:
                    df = pd.read_csv(filepath, encoding='latin1', on_bad_lines='skip')
            else:
                df = pd.read_excel(filepath)
        except Exception as e:
            raise ValueError(f"Could not read file: {e}")

        # Map Headers
        if table_name in Config.HEADER_MAP:
            mapping = Config.HEADER_MAP[table_name]
            df.rename(columns=mapping, inplace=True)
        
        # Normalize columns
        df.columns = [self.clean_name(col) for col in df.columns]
        
        # Simple data cleaning
        df = df.astype(str) # Convert all to string for staging to avoid type errors
        df = df.replace({'nan': None, 'None': None, 'Null': None, 'NULL': None})
        
        df.to_sql(table_name, self.engine, if_exists='replace', index=False)
        return table_name

    def transform_to_schema(self):
        logger.info("⚙️  Running Transformations (Staging -> Production)...")
        with self.engine.begin() as conn:
            # 1. Get Excel Source ID (High Priority)
            excel_source_id = conn.execute(text("SELECT source_id FROM config.data_sources WHERE source_name = 'excel_import'")).scalar() or 1

            # 2. PRODUCTS (Main DB) -> inventory.products
            logger.info("   -> Transforming Products...")
            conn.execute(text("""
                INSERT INTO inventory.products (
                    sku, name, category, full_description, brand, manufacturer, 
                    regulatory_status, upsell_hints, substitute_hints, primary_source_id
                )
                SELECT DISTINCT 
                    sku, name, 
                    COALESCE(UPPER(category), 'GENERAL_MEDICAL'), 
                    description, brand, manufacturer,
                    regulatory_status, upsell_hints, substitute_hints,
                    :source_id
                FROM stg_db_4_g
                WHERE sku IS NOT NULL
                ON CONFLICT (sku) DO UPDATE SET 
                    name = EXCLUDED.name,
                    full_description = EXCLUDED.full_description,
                    upsell_hints = EXCLUDED.upsell_hints,
                    substitute_hints = EXCLUDED.substitute_hints,
                    primary_source_id = EXCLUDED.primary_source_id;
            """), {"source_id": excel_source_id})

            # 3. OFFERINGS (Price/Stock) -> inventory.product_offerings
            logger.info("   -> Transforming Offerings...")
            conn.execute(text("""
                INSERT INTO inventory.product_offerings (
                    product_id, supplier_id, supplier_sku, price, stock_status, 
                    min_order_quantity, lead_time_days, source_id
                )
                SELECT 
                    p.product_id,
                    1, -- Default Supplier (SocioMed)
                    p.sku,
                    CAST(REGEXP_REPLACE(stg.price::text, '[^0-9.]', '', 'g') AS DECIMAL),
                    stg.stock_status,
                    CAST(NULLIF(stg.min_order_quantity, '') AS INTEGER),
                    CAST(NULLIF(stg.lead_time_days, '') AS INTEGER),
                    :source_id
                FROM stg_db_4_g stg
                JOIN inventory.products p ON stg.sku = p.sku
                WHERE stg.price IS NOT NULL
                ON CONFLICT (product_id, supplier_id, supplier_sku) DO UPDATE SET
                    price = EXCLUDED.price,
                    stock_status = EXCLUDED.stock_status,
                    quantity_on_hand = CASE WHEN EXCLUDED.stock_status = 'In Stock' THEN 100 ELSE 0 END,
                    source_id = EXCLUDED.source_id; 
            """), {"source_id": excel_source_id})

            # 4. RELATIONSHIPS (New Step: Linking Equipment to Consumables/Accessories)
            logger.info("   -> Transforming Product Relationships...")
            
            # Logic: Split comma-separated SKUs in 'upsell_hints' (Compatible With) 
            # and automatically detect type based on the child category.
            conn.execute(text("""
                INSERT INTO inventory.product_relationships (
                    parent_product_id, child_product_id, relationship_type, source_id
                )
                SELECT DISTINCT
                    p_parent.product_id,
                    p_child.product_id,
                    CASE 
                        -- Auto-detect relationship type based on child category
                        WHEN p_child.category IN ('CONSUMABLES', 'REAGENTS', 'PHARMACEUTICALS', 'DISPOSABLES') THEN 'CONSUMABLE'
                        WHEN p_child.category IN ('ACCESSORIES', 'COMPONENTS', 'SPARE_PARTS') THEN 'ACCESSORY'
                        ELSE 'COMPLEMENTARY'
                    END,
                    :source_id
                FROM stg_db_4_g stg
                JOIN inventory.products p_parent ON stg.sku = p_parent.sku
                -- Split comma-separated list into rows
                CROSS JOIN LATERAL regexp_split_to_table(stg.upsell_hints, ',\\s*') AS related_sku
                JOIN inventory.products p_child ON p_child.sku = related_sku
                WHERE stg.upsell_hints IS NOT NULL
                ON CONFLICT (parent_product_id, child_product_id, relationship_type) DO NOTHING;
            """), {"source_id": excel_source_id})

            # 5. SUBSTITUTES (From 'Substitute Item' column)
            logger.info("   -> Transforming Substitutes...")
            conn.execute(text("""
                INSERT INTO inventory.product_relationships (
                    parent_product_id, child_product_id, relationship_type, source_id
                )
                SELECT DISTINCT
                    p_parent.product_id,
                    p_child.product_id,
                    'SUBSTITUTE',
                    :source_id
                FROM stg_db_4_g stg
                JOIN inventory.products p_parent ON stg.sku = p_parent.sku
                CROSS JOIN LATERAL regexp_split_to_table(stg.substitute_hints, ',\\s*') AS related_sku
                JOIN inventory.products p_child ON p_child.sku = related_sku
                WHERE stg.substitute_hints IS NOT NULL
                ON CONFLICT (parent_product_id, child_product_id, relationship_type) DO NOTHING;
            """), {"source_id": excel_source_id})
            
    def _table_exists(self, conn, table_name):
        return conn.execute(text(f"SELECT to_regclass('{table_name}')")).scalar() is not None

    def run(self):
        logger.info(f"🚀 Starting ETL Job. Watching: {Config.BASE_DIR}")
        files = []
        for ext in ["*.csv", "*.CSV", "*.xlsx", "*.XLSX"]:
            files.extend(glob.glob(os.path.join(Config.BASE_DIR, ext)))
            # Also check subdirectories for extracted files
            files.extend(glob.glob(os.path.join(Config.BASE_DIR, "**", ext), recursive=True))

        if not files:
            logger.warning("⚠️  No files found.")
            return

        for filepath in files:
            if "processed" in filepath or "failed" in filepath: continue
            try:
                self.load_staging(filepath)
                # Move logic can be uncommented in production
                # self.move_file(filepath, Config.PROCESSED_DIR) 
            except Exception as e:
                logger.error(f"❌ Error loading {filepath}: {e}")

        try:
            self.transform_to_schema()
            logger.info("✅ ETL Complete.")
        except Exception as e:
            logger.error(f"❌ Transformation Failed: {e}")
            raise

if __name__ == "__main__":
    SocioMedETL().run()
