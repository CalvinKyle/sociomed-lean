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
        """ Executes the complex logic to populate production tables from staging. """
        logger.info("⚙️  Running Transformations (Staging -> Production)...")
        
        with self.engine.begin() as conn:
            # 1. SETUP: Ensure Data Source Exists
            conn.execute(text("""
                INSERT INTO config.data_sources (source_name, source_type, priority, description)
                VALUES ('excel_import', 'PRIMARY', 10, 'Main Excel Bulk Import')
                ON CONFLICT (source_name) DO NOTHING;
            """))
            source_id = conn.execute(text("SELECT source_id FROM config.data_sources WHERE source_name = 'excel_import'")).scalar()

            # 2. SUPPLIERS (Merge Supply Contacts & Man/Dis)
            logger.info("   -> Merging Suppliers...")
            # From Supply Contacts
            if self._table_exists(conn, 'stg_supply_contacts'):
                conn.execute(text("""
                    INSERT INTO inventory.suppliers (
                        name, contact_email, contact_phone, business_type, 
                        address_line1, lead_time_days, type, data_source_id
                    )
                    SELECT DISTINCT
                        name, contact_email, contact_phone, business_type, 
                        address_line1, CAST(NULLIF(regexp_replace(lead_time_days, '[^0-9]', '', 'g'), '') AS INTEGER),
                        'EXTERNAL', :source_id
                    FROM stg_supply_contacts
                    WHERE name IS NOT NULL
                    ON CONFLICT (name) DO UPDATE SET 
                        contact_email = EXCLUDED.contact_email,
                        contact_phone = EXCLUDED.contact_phone;
                """), {"source_id": source_id})

            # 3. PRODUCTS (Main DB & Katsan)
            logger.info("   -> Transforming Products...")
            # From Main DB (db_4_g)
            if self._table_exists(conn, 'stg_db_4_g'):
                conn.execute(text("""
                    INSERT INTO inventory.products (
                        sku, name, category, description, brand, manufacturer, 
                        regulatory_status, primary_source_id
                    )
                    SELECT DISTINCT 
                        sku, name, 
                        COALESCE(category, 'GENERAL_MEDICAL'), 
                        description, brand, manufacturer,
                        regulatory_status, :source_id
                    FROM stg_db_4_g
                    WHERE sku IS NOT NULL
                    ON CONFLICT (sku) DO UPDATE SET 
                        name = EXCLUDED.name,
                        description = EXCLUDED.description,
                        brand = EXCLUDED.brand;
                """), {"source_id": source_id})

            # From Katsan (Specialty)
            if self._table_exists(conn, 'stg_katsan_pdts'):
                conn.execute(text("""
                    INSERT INTO inventory.products (sku, name, description, category, brand, primary_source_id)
                    SELECT DISTINCT sku, name, description, category, brand, :source_id
                    FROM stg_katsan_pdts
                    WHERE sku IS NOT NULL
                    ON CONFLICT (sku) DO UPDATE SET description = EXCLUDED.description;
                """), {"source_id": source_id})

            # 4. CUSTOMERS / PREMISES (Sales.Users)
            logger.info("   -> Loading Premises as Users...")
            if self._table_exists(conn, 'stg_premises'):
                conn.execute(text("""
                    INSERT INTO sales.users (
                        phone_number, full_name, organization_name, organization_type, 
                        district, region, address, premise_no, user_type
                    )
                    SELECT DISTINCT 
                        COALESCE(phone_number, 'UNKNOWN-' || premise_no), -- Ensure unique constraint isn't violated
                        COALESCE(contact_person_name, 'Admin'),
                        organization_name, 
                        organization_type, 
                        district, region, address, premise_no, 'BUYER'
                    FROM stg_premises
                    WHERE organization_name IS NOT NULL
                    ON CONFLICT (phone_number) DO UPDATE SET
                        organization_name = EXCLUDED.organization_name,
                        district = EXCLUDED.district;
                """))

            # 5. PRODUCT OFFERINGS (Prices & Stock)
            logger.info("   -> Updating Prices & Inventory...")
            if self._table_exists(conn, 'stg_db_4_g'):
                # Ensure local SocioMed supplier exists
                socio_id = conn.execute(text("SELECT supplier_id FROM inventory.suppliers WHERE type='SOCIO_MED' LIMIT 1")).scalar() or 1
                
                conn.execute(text("""
                    INSERT INTO inventory.product_offerings (
                        product_id, supplier_id, price, stock_status, 
                        min_order_quantity, lead_time_days, source_id
                    )
                    SELECT 
                        p.product_id,
                        :supplier_id,
                        CAST(NULLIF(regexp_replace(stg.price, '[^0-9.]', '', 'g'), '') AS DECIMAL),
                        CASE 
                            WHEN stg.stock_status ILIKE '%%Inventory%%' THEN 'IN_STOCK'
                            ELSE 'OUT_OF_STOCK'
                        END,
                        CAST(NULLIF(regexp_replace(stg.min_order_quantity, '[^0-9]', '', 'g'), '') AS INTEGER),
                        CAST(NULLIF(regexp_replace(stg.lead_time_days, '[^0-9]', '', 'g'), '') AS INTEGER),
                        :source_id
                    FROM stg_db_4_g stg
                    JOIN inventory.products p ON stg.sku = p.sku
                    WHERE stg.price IS NOT NULL
                    ON CONFLICT (product_id, supplier_id) DO UPDATE SET
                        price = EXCLUDED.price,
                        stock_status = EXCLUDED.stock_status,
                        quantity_on_hand = CASE WHEN EXCLUDED.stock_status = 'IN_STOCK' THEN 50 ELSE 0 END;
                """), {"supplier_id": socio_id, "source_id": source_id})

            # 6. BUNDLES & KITS
            logger.info("   -> Creating Bundles...")
            if self._table_exists(conn, 'stg_bund_kits'):
                # Create Bundle Headers
                conn.execute(text("""
                    INSERT INTO inventory.bundles (bundle_code, name, source_id)
                    SELECT DISTINCT kit_code, name, :source_id
                    FROM stg_bund_kits
                    WHERE kit_code IS NOT NULL
                    ON CONFLICT (bundle_code) DO NOTHING;
                """), {"source_id": source_id})

                # Create Bundle Items
                conn.execute(text("""
                    INSERT INTO inventory.bundle_items (bundle_id, product_id, quantity, discount_override)
                    SELECT DISTINCT 
                        b.bundle_id, 
                        p.product_id, 
                        CAST(NULLIF(k.quantity, '') AS INTEGER),
                        CAST(NULLIF(regexp_replace(k.discount_percent, '[^0-9.]', '', 'g'), '') AS DECIMAL)
                    FROM stg_bund_kits k
                    JOIN inventory.bundles b ON k.kit_code = b.bundle_code
                    JOIN inventory.products p ON k.component_sku = p.sku
                    ON CONFLICT (bundle_id, product_id) DO NOTHING;
                """))

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
