-- ==================================================================================
-- SOCIO-MED MARKETPLACE SCHEMA
-- Version: 2.3 (Refined for UGX & Inventory Ops)
-- Updates: UGX Default, Inventory Counters, Price Tiers, Bot State
-- ==================================================================================

-- 1. CLEAN UP
DROP TABLE IF EXISTS audit_logs CASCADE;
DROP TABLE IF EXISTS price_tiers CASCADE;
DROP TABLE IF EXISTS quote_items CASCADE;
DROP TABLE IF EXISTS quotes CASCADE;
DROP TABLE IF EXISTS bundle_items CASCADE;
DROP TABLE IF EXISTS bundles CASCADE;
DROP TABLE IF EXISTS product_relationships CASCADE;
DROP TABLE IF EXISTS interactions CASCADE;
DROP TABLE IF EXISTS product_offerings CASCADE;
DROP TABLE IF EXISTS products CASCADE;
DROP TABLE IF EXISTS users CASCADE;
DROP TABLE IF EXISTS suppliers CASCADE;

-- 2. SUPPLIERS
CREATE TABLE suppliers (
    supplier_id SERIAL PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    country VARCHAR(100),
    contact_email VARCHAR(255),
    contact_phone VARCHAR(50),
    website VARCHAR(255),
    type VARCHAR(20) CHECK (type IN ('SOCIO_MED', 'PARTNER')) NOT NULL,
    commission_rate DECIMAL(5,2) DEFAULT 0.00, 
    certifications TEXT, 
    api_integration_details JSONB, 
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 3. PRODUCT CATALOG (Master List)
CREATE TABLE products (
    product_id SERIAL PRIMARY KEY,
    sku VARCHAR(100) UNIQUE NOT NULL, 
    name VARCHAR(500) NOT NULL,
    brand VARCHAR(200),
    manufacturer VARCHAR(200), 
    
    -- ENHANCEMENT 1: STRICT CATEGORIES
    category VARCHAR(50) CHECK (category IN (
        'medical equipment', 
        'devices', 
        'consumables', 
        'surgical instruments', 
        'reagents',
        'general' -- Fallback
    )),
    
    subcategory VARCHAR(200), 
    description TEXT, 
    unit_of_measure VARCHAR(50) DEFAULT 'UNIT', 
    
    -- Medical Compliance
    requires_prescription BOOLEAN DEFAULT FALSE,
    regulatory_status VARCHAR(100), 
    
    -- Technical Data
    specifications JSONB, 
    
    -- ENHANCEMENT 2: UPSELL HINTS (Stores raw text like "Use with Catheter X")
    upsell_hints TEXT, 
    
    -- ENHANCEMENT 3: DATA GOVERNANCE (The Logic Engine)
    data_source VARCHAR(50), -- e.g., 'INVENTORY_EXCEL', 'GEMINI_PDF'
    trust_score INT DEFAULT 0, -- 100 = Excel (Verified), 10 = PDF (AI Guess)
    
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    
    -- ENHANCEMENT 4: TRIGGER TO UPDATE TIMESTAMP
	CREATE OR REPLACE FUNCTION update_timestamp()
	RETURNS TRIGGER AS $$
	BEGIN
		NEW.updated_at = NOW();
		RETURN NEW;
	END;
	$$ LANGUAGE plpgsql;

	CREATE TRIGGER trg_products_timestamp
	BEFORE UPDATE ON products
	FOR EACH ROW EXECUTE FUNCTION update_timestamp()
);

-- 4. PRODUCT RELATIONSHIPS
CREATE TABLE product_relationships (
    relationship_id SERIAL PRIMARY KEY,
    parent_product_id INT REFERENCES products(product_id) ON DELETE CASCADE,
    child_product_id INT REFERENCES products(product_id) ON DELETE CASCADE,
    
    relationship_type VARCHAR(50) CHECK (relationship_type IN ('UPSELL', 'CONSUMABLE', 'ACCESSORY', 'SUBSTITUTE', 'CROSS_SELL')),
    
    quantity_recommended INT DEFAULT 1,
    strength DECIMAL(3,2) DEFAULT 1.0, 
    reason_text VARCHAR(255), 
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(parent_product_id, child_product_id, relationship_type)
);

-- 5. BUNDLES
CREATE TABLE bundles (
    bundle_id SERIAL PRIMARY KEY,
    name VARCHAR(300) NOT NULL, 
    description TEXT,
    discount_percent DECIMAL(5,2) DEFAULT 0.00,
    total_price DECIMAL(14,2), -- Increased precision for UGX
    currency VARCHAR(3) DEFAULT 'UGX', -- CHANGED: Default to UGX
    valid_from DATE DEFAULT CURRENT_DATE,
    valid_until DATE,
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE bundle_items (
    bundle_item_id SERIAL PRIMARY KEY,
    bundle_id INT REFERENCES bundles(bundle_id) ON DELETE CASCADE,
    product_id INT REFERENCES products(product_id),
    quantity INT DEFAULT 1,
    UNIQUE(bundle_id, product_id)
);

-- 6. PRODUCT OFFERINGS (Inventory & Pricing)
CREATE TABLE product_offerings (
    offering_id SERIAL PRIMARY KEY,
    product_id INT REFERENCES products(product_id) ON DELETE CASCADE,
    supplier_id INT REFERENCES suppliers(supplier_id) ON DELETE SET NULL,
    supplier_sku VARCHAR(100), 
    
    -- Commercials
    price DECIMAL(14,2) NOT NULL, -- Increased precision for UGX
    currency VARCHAR(3) DEFAULT 'UGX', -- CHANGED: Default to UGX
    
    -- Inventory Management (NEW)
    quantity_on_hand INT DEFAULT 0 CHECK (quantity_on_hand >= 0), -- Actual physical stock
    quantity_reserved INT DEFAULT 0 CHECK (quantity_reserved >= 0), -- Stock held in unpaid quotes
    moq INT DEFAULT 1, 
    
    -- Logistics
    stock_status VARCHAR(50) DEFAULT 'IN_STOCK', 
    lead_time_days INT DEFAULT 7,
    location_bin VARCHAR(50), 
    
    -- Service
    warranty_months INT DEFAULT 0,
    installation_included BOOLEAN DEFAULT FALSE,
    valid_until DATE, 
    
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    
    -- Helper to identify Direct Sales
    is_socio_med_stock BOOLEAN GENERATED ALWAYS AS (
        supplier_id = (SELECT supplier_id FROM suppliers WHERE type = 'SOCIO_MED' LIMIT 1)
    ) STORED,
    
    UNIQUE(product_id, supplier_id)
);

-- 7. PRICE TIERS (NEW: Wholesale Logic)
-- Allows: "Buy 1 @ 50,000 UGX, Buy 10 @ 45,000 UGX"
CREATE TABLE price_tiers (
    tier_id SERIAL PRIMARY KEY,
    offering_id INT REFERENCES product_offerings(offering_id) ON DELETE CASCADE,
    min_quantity INT NOT NULL,
    unit_price DECIMAL(14,2) NOT NULL,
    currency VARCHAR(3) DEFAULT 'UGX',
    UNIQUE(offering_id, min_quantity)
);

-- 8. USERS (CRM)
CREATE TABLE users (
    user_id SERIAL PRIMARY KEY,
    phone_number VARCHAR(30) UNIQUE NOT NULL, 
    full_name VARCHAR(200), 
    organization VARCHAR(300), 
    email VARCHAR(255),
    country VARCHAR(100),
    tax_id VARCHAR(50),
    address TEXT,
    user_type VARCHAR(20) DEFAULT 'buyer' CHECK (user_type IN ('buyer', 'admin', 'supplier_rep')),
    
    -- Bot State Management (NEW)
    bot_state JSONB DEFAULT '{}', -- Stores context: {"current_flow": "quote", "step": "confirm_qty"}
    
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 9. INTERACTIONS (Chat Logs)
CREATE TABLE interactions (
    interaction_id SERIAL PRIMARY KEY,
    user_id INT REFERENCES users(user_id) ON DELETE CASCADE,
    message_text TEXT,
    intent_detected VARCHAR(100), 
    product_inquired INT REFERENCES products(product_id),
    response_text TEXT,
    is_referral_generated BOOLEAN DEFAULT FALSE, 
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 10. QUOTES (Invoicing)
CREATE TABLE quotes (
    quote_id SERIAL PRIMARY KEY,
    user_id INT REFERENCES users(user_id),
    quote_number VARCHAR(50) UNIQUE, 
    status VARCHAR(20) DEFAULT 'DRAFT' CHECK (status IN ('DRAFT', 'SENT', 'CONFIRMED', 'EXPIRED', 'PAID')),
    
    total_amount DECIMAL(16,2), -- Large precision for UGX totals
    currency VARCHAR(3) DEFAULT 'UGX', -- CHANGED: Default to UGX
    exchange_rate DECIMAL(10,4) DEFAULT 1.0, -- To track USD conversion if needed
    
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    valid_until DATE,
    expires_at TIMESTAMP
);

CREATE TABLE quote_items (
    item_id SERIAL PRIMARY KEY,
    quote_id INT REFERENCES quotes(quote_id) ON DELETE CASCADE,
    offering_id INT REFERENCES product_offerings(offering_id),
    quantity INT NOT NULL,
    unit_price DECIMAL(14,2) NOT NULL,
    line_total DECIMAL(16,2) GENERATED ALWAYS AS (quantity * unit_price) STORED
);

-- 11. AUDIT LOGS (NEW: Compliance)
-- Tracks who changed prices or stock
CREATE TABLE audit_logs (
    log_id SERIAL PRIMARY KEY,
    table_name VARCHAR(50),
    record_id INT,
    action VARCHAR(10), -- 'UPDATE', 'DELETE', 'INSERT'
    changed_by INT REFERENCES users(user_id), -- Optional, null if system
    old_value JSONB,
    new_value JSONB,
    changed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 12. SEQUENCES & FUNCTIONS

-- Quote Numbering Sequence
CREATE SEQUENCE quotes_seq START 1001;

CREATE OR REPLACE FUNCTION generate_quote_number()
RETURNS TRIGGER AS $$
BEGIN
    -- Format: QT-YYYY-1001 (e.g., QT-2025-1001)
    NEW.quote_number := 'QT-' || EXTRACT(YEAR FROM CURRENT_DATE) || '-' || LPAD(nextval('quotes_seq')::TEXT, 4, '0');
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_quote_number
BEFORE INSERT ON quotes
FOR EACH ROW EXECUTE FUNCTION generate_quote_number();

-- Inventory Reservation Function (NEW)
-- Automatically moves stock from 'On Hand' to 'Reserved' when a quote is Confirmed
CREATE OR REPLACE FUNCTION reserve_inventory()
RETURNS TRIGGER AS $$
BEGIN
    IF NEW.status = 'CONFIRMED' AND OLD.status != 'CONFIRMED' THEN
        -- Move stock for each item in the quote
        UPDATE product_offerings po
        SET quantity_on_hand = quantity_on_hand - qi.quantity,
            quantity_reserved = quantity_reserved + qi.quantity
        FROM quote_items qi
        WHERE qi.quote_id = NEW.quote_id 
          AND po.offering_id = qi.offering_id;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_reserve_inventory
AFTER UPDATE ON quotes
FOR EACH ROW EXECUTE FUNCTION reserve_inventory();

-- 13. INDEXES
CREATE INDEX idx_products_fts ON products USING gin(to_tsvector('english', name || ' ' || COALESCE(short_description, '')));
CREATE INDEX idx_products_name_fuzzy ON products USING gin (name gin_trgm_ops);
CREATE INDEX idx_offerings_price ON product_offerings(price);
CREATE INDEX idx_users_phone ON users(phone_number);

-- ==================================================================================
-- INITIAL DATA SEEDING (With UGX Prices)
-- ==================================================================================

-- Core Suppliers
INSERT INTO suppliers (supplier_id, name, type, commission_rate, country) 
OVERRIDING SYSTEM VALUE VALUES 
(1, 'SocioMed', 'SOCIO_MED', 0.00, 'Uganda'),
(2, 'Zelus Medical Solutions', 'PARTNER', 12.50, 'Uganda/Germany'),
(3, 'Global Imaging Partners', 'PARTNER', 10.00, 'USA');

SELECT setval('suppliers_supplier_id_seq', (SELECT MAX(supplier_id) FROM suppliers));

-- Sample Products
INSERT INTO products (sku, name, short_description, category, subcategory) VALUES
('CATH-HEMO-12CM', 'Hemodialysis Catheter', 'Double Lumen, 12cm', 'Nephrology', 'Catheters'),
('GLOV-NIT-100', 'Nitrile Examination Gloves', 'Powder-free, Box of 100', 'Consumables', 'Gloves');

-- Sample Offerings (Prices in UGX)
-- Assuming approx exchange rate 1 USD = 3,700 UGX
INSERT INTO product_offerings (product_id, supplier_id, price, quantity_on_hand, moq, stock_status) VALUES
(1, 1, 166500.00, 50, 10, 'IN_STOCK'),  -- ~ $45 USD
(2, 1, 33300.00, 500, 5, 'IN_STOCK');   -- ~ $9 USD

-- Sample Price Tier
-- If you buy 50+ catheters, price drops to 150,000 UGX
INSERT INTO price_tiers (offering_id, min_quantity, unit_price) VALUES
((SELECT offering_id FROM product_offerings WHERE product_id=1 LIMIT 1), 50, 150000.00);

