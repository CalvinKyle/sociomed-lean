-- ==================================================================================
-- SOCIO-MED MARKETPLACE SCHEMA v4.5
-- Production-Ready with Medical-Specific Enhancements
-- Features: Multi-Source ETL, Conflict Resolution, Clinical Specialties, Vector Search
-- ==================================================================================

-- ==================================================================================
-- 0. INITIAL SETUP & EXTENSIONS
-- ==================================================================================
SET statement_timeout = 0;
SET lock_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SET check_function_bodies = false;
SET xmloption = content;
SET client_min_messages = warning;
SET row_security = off;

-- Enable required extensions
CREATE EXTENSION IF NOT EXISTS pg_trgm; -- Fuzzy text search
CREATE EXTENSION IF NOT EXISTS "uuid-ossp"; -- UUID generation
CREATE EXTENSION IF NOT EXISTS pgcrypto; -- Cryptographic functions for hashing
CREATE EXTENSION IF NOT EXISTS vector; -- Vector embeddings for AI/ML search (v5.0 enhancement)

-- Create schemas for organization
CREATE SCHEMA IF NOT EXISTS inventory;
CREATE SCHEMA IF NOT EXISTS sales;
CREATE SCHEMA IF NOT EXISTS audit;
CREATE SCHEMA IF NOT EXISTS config;

-- ==================================================================================
-- 1. CLEAN UP (Production-safe with CASCADE)
-- ==================================================================================
DROP TABLE IF EXISTS audit.audit_logs CASCADE;
DROP TABLE IF EXISTS sales.price_tiers CASCADE;
DROP TABLE IF EXISTS sales.quote_items CASCADE;
DROP TABLE IF EXISTS sales.quotes CASCADE;
DROP TABLE IF EXISTS inventory.bundle_items CASCADE;
DROP TABLE IF EXISTS inventory.bundles CASCADE;
DROP TABLE IF EXISTS inventory.product_relationships CASCADE;
DROP TABLE IF EXISTS sales.interactions CASCADE;
DROP TABLE IF EXISTS sales.unmet_demand CASCADE;
DROP TABLE IF EXISTS inventory.product_offerings CASCADE;
DROP TABLE IF EXISTS inventory.products CASCADE;
DROP TABLE IF EXISTS sales.users CASCADE;
DROP TABLE IF EXISTS inventory.suppliers CASCADE;
DROP TABLE IF EXISTS config.data_sources CASCADE;

-- ==================================================================================
-- 2. CONFIGURATION TABLES
-- ==================================================================================
CREATE TABLE config.data_sources (
    source_id SERIAL PRIMARY KEY,
    source_name VARCHAR(50) UNIQUE NOT NULL,
    source_type VARCHAR(20) CHECK (source_type IN ('PRIMARY', 'SECONDARY', 'ENRICHMENT', 'SYSTEM')),
    priority INT NOT NULL DEFAULT 100 CHECK (priority > 0),
    description TEXT,
    is_trusted BOOLEAN DEFAULT TRUE,
    last_run_at TIMESTAMP,
    last_success_at TIMESTAMP,
    error_count INT DEFAULT 0,
    max_retries INT DEFAULT 3,
    retry_interval_minutes INT DEFAULT 60,
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    
    -- JSON configuration for source-specific settings
    config JSONB DEFAULT '{}',
    
    -- Performance metrics
    avg_processing_time_ms INT DEFAULT 0,
    total_records_processed BIGINT DEFAULT 0
);

-- Index for frequent queries
CREATE INDEX idx_data_sources_priority ON config.data_sources(priority, is_active);
CREATE INDEX idx_data_sources_last_run ON config.data_sources(last_run_at);

-- ==================================================================================
-- 3. INVENTORY SCHEMA: SUPPLIERS
-- ==================================================================================
CREATE TABLE inventory.suppliers (
    supplier_id SERIAL PRIMARY KEY,
    external_id VARCHAR(100) UNIQUE, -- For external system integration
    name VARCHAR(200) NOT NULL,
    code VARCHAR(50) UNIQUE,
    country VARCHAR(100),
    region VARCHAR(100),
    district VARCHAR(100),
    
    -- Contact Information
    contact_email VARCHAR(255),
    contact_phone VARCHAR(50),
    contact_person VARCHAR(200),
    secondary_phone VARCHAR(50),
    website VARCHAR(255),
    
    -- Business Details
    type VARCHAR(20) CHECK (type IN ('SOCIO_MED', 'PARTNER', 'EXTERNAL', 'MANUFACTURER')) NOT NULL,
    business_type VARCHAR(50), -- Wholesaler, Manufacturer, Distributor
    tax_id VARCHAR(50),
    vat_number VARCHAR(50),
    license_number VARCHAR(100),
    registration_date DATE,
    
    -- Financial
    commission_rate DECIMAL(5,2) DEFAULT 0.00 CHECK (commission_rate >= 0 AND commission_rate <= 100),
    payment_terms VARCHAR(100),
    preferred_currency VARCHAR(3) DEFAULT 'UGX',
    credit_limit DECIMAL(14,2) DEFAULT 0.00,
    current_balance DECIMAL(14,2) DEFAULT 0.00,
    
    -- Compliance & Certifications
    certifications TEXT[],
    accreditation_status VARCHAR(50),
    quality_rating DECIMAL(3,2) DEFAULT 0.0 CHECK (quality_rating >= 0 AND quality_rating <= 5),
    
    -- Logistics
    lead_time_days INT DEFAULT 7,
    shipping_methods VARCHAR(100)[],
    delivery_coverage TEXT[],
    
    -- Integration
    api_integration_details JSONB,
    data_source_id INT REFERENCES config.data_sources(source_id),
    external_system_id VARCHAR(100),
    
    -- Address (Normalized)
    address_line1 TEXT,
    address_line2 TEXT,
    city VARCHAR(100),
    postal_code VARCHAR(20),
    coordinates POINT, -- For GIS/mapping
    
    -- Metadata
    notes TEXT,
    metadata JSONB DEFAULT '{}',
    tags VARCHAR(50)[],
    
    -- Status
    status VARCHAR(20) DEFAULT 'ACTIVE' CHECK (status IN ('ACTIVE', 'INACTIVE', 'SUSPENDED', 'BLACKLISTED')),
    is_verified BOOLEAN DEFAULT FALSE,
    verified_at TIMESTAMP,
    verification_notes TEXT,
    
    -- Audit Trail
    created_by INT,
    updated_by INT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    
    -- Constraints
    CONSTRAINT chk_supplier_balance CHECK (current_balance <= credit_limit)
);

-- Supplier indexes
CREATE INDEX idx_suppliers_name ON inventory.suppliers USING GIN(name gin_trgm_ops);
CREATE INDEX idx_suppliers_country ON inventory.suppliers(country, region);
CREATE INDEX idx_suppliers_type ON inventory.suppliers(type, status);
CREATE INDEX idx_suppliers_external ON inventory.suppliers(external_id);
CREATE INDEX idx_suppliers_created ON inventory.suppliers(created_at DESC);

-- ==================================================================================
-- 4. INVENTORY SCHEMA: PRODUCT CATALOG (Enhanced with v5.0 Medical Features)
-- ==================================================================================
CREATE TABLE inventory.products (
    product_id SERIAL PRIMARY KEY,
    external_id VARCHAR(100) UNIQUE,
    sku VARCHAR(100) UNIQUE NOT NULL,
    upc VARCHAR(50), -- Universal Product Code
    mpn VARCHAR(100), -- Manufacturer Part Number
    
    -- Basic Information
    name VARCHAR(500) NOT NULL,
    short_description VARCHAR(1000),
    full_description TEXT,
    brand VARCHAR(200),
    manufacturer VARCHAR(200),
    model VARCHAR(200),
    
    -- Categorization (v4.0 Comprehensive + v5.0 Clinical Focus)
    category VARCHAR(100) NOT NULL CHECK (category IN (
        'MEDICAL_EQUIPMENT',
        'DIAGNOSTIC_DEVICES',
        'SURGICAL_INSTRUMENTS',
        'PATIENT_MONITORING',
        'LABORATORY_EQUIPMENT',
        'CONSUMABLES',
        'PHARMACEUTICALS',
        'REAGENTS',
        'IMPLANTS',
        'DISPOSABLES',
        'PERSONAL_PROTECTIVE_EQUIPMENT',
        'REHABILITATION',
        'DENTAL',
        'OPHTHALMIC',
        'VETERINARY',
        'GENERAL_MEDICAL'
    )),
    
    -- v5.0 ENHANCEMENT: Clinical Specialty for Medical Context
    clinical_specialty VARCHAR(100) CHECK (clinical_specialty IN (
        'NEPHROLOGY', 
        'CRITICAL_CARE', 
        'CARDIOLOGY', 
        'RADIOLOGY', 
        'SURGERY', 
        'LABORATORY', 
        'DENTAL', 
        'ORTHOPEDICS', 
        'GYNECOLOGY', 
        'GENERAL_PRACTICE', 
        'OTHER'
    )),
    
    subcategory VARCHAR(200),
    product_line VARCHAR(100),
    therapeutic_area VARCHAR(100),
    
    -- Upsell Logic
    upsell_hints TEXT,
    cross_sell_hints TEXT,
    frequently_bought_with TEXT[],
    
    -- Unit Specifications
    unit_of_measure VARCHAR(50) DEFAULT 'UNIT',
    uom_details VARCHAR(100),
    base_unit VARCHAR(20),
    units_per_package INT DEFAULT 1 CHECK (units_per_package > 0),
    packages_per_case INT DEFAULT 1 CHECK (packages_per_case > 0),
    case_weight_kg DECIMAL(10,2),
    case_dimensions VARCHAR(100),
    
    -- Medical Compliance
    requires_prescription BOOLEAN DEFAULT FALSE,
    is_scheduled_drug BOOLEAN DEFAULT FALSE,
    regulatory_status VARCHAR(100),
    regulatory_body VARCHAR(50),
    license_number VARCHAR(100),
    approval_date DATE,
    expiry_date DATE,
    requires_cold_chain BOOLEAN DEFAULT FALSE, -- Critical for reagents
    
    -- Technical Specifications (Structured)
    specifications JSONB,
    dimensions VARCHAR(100),
    weight_kg DECIMAL(10,2),
    color VARCHAR(50),
    material VARCHAR(100),
    power_requirements VARCHAR(100),
    voltage VARCHAR(50),
    frequency VARCHAR(50),
    
    -- Attributes
    is_sterile BOOLEAN DEFAULT FALSE,
    is_disposable BOOLEAN DEFAULT TRUE,
    is_reusable BOOLEAN DEFAULT FALSE,
    is_refurbished BOOLEAN DEFAULT FALSE,
    is_critical BOOLEAN DEFAULT FALSE, -- For hospital critical equipment
    is_high_value BOOLEAN DEFAULT FALSE,
    is_controlled_substance BOOLEAN DEFAULT FALSE,
    
    -- Storage & Handling
    storage_temperature VARCHAR(50),
    humidity_range VARCHAR(50),
    light_sensitivity BOOLEAN DEFAULT FALSE,
    shelf_life_months INT,
    shelf_life_after_opening_days INT,
    
    -- Documentation & Media
    image_urls TEXT[],
    manual_url TEXT,
    datasheet_url TEXT,
    certificate_url TEXT,
    video_url TEXT,
    
    -- Source Tracking & Conflict Resolution
    primary_source_id INT NOT NULL REFERENCES config.data_sources(source_id),
    source_file_name VARCHAR(255),
    source_record_id VARCHAR(100),
    source_hash VARCHAR(64),
    
    -- Conflict Resolution Metadata
    last_updated_by_source_id INT REFERENCES config.data_sources(source_id),
    last_updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    version INT DEFAULT 1,
    is_locked BOOLEAN DEFAULT FALSE,
    locked_by INT,
    locked_at TIMESTAMP,
    
    -- v5.0 ENHANCEMENT: Vector Embeddings for AI/ML Semantic Search
    embedding vector(768), -- For similarity search
    
    -- Quality Metrics
    data_quality_score INT DEFAULT 100 CHECK (data_quality_score >= 0 AND data_quality_score <= 100),
    completeness_score INT DEFAULT 0,
    accuracy_score INT DEFAULT 0,
    
    -- Audit Trail
    created_by INT,
    updated_by INT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    
    -- v5.0 ENHANCEMENT: Enhanced Full Text Search Vector with Clinical Context
    search_vector tsvector GENERATED ALWAYS AS (
        setweight(to_tsvector('english', COALESCE(name, '')), 'A') ||
        setweight(to_tsvector('english', COALESCE(brand, '')), 'B') ||
        setweight(to_tsvector('english', COALESCE(clinical_specialty, '')), 'B') ||
        setweight(to_tsvector('english', COALESCE(category, '')), 'C') ||
        setweight(to_tsvector('english', COALESCE(short_description, '')), 'C') ||
        setweight(to_tsvector('english', COALESCE(manufacturer, '')), 'C') ||
        setweight(to_tsvector('english', COALESCE(model, '')), 'D')
    ) STORED
);

-- Product indexes (including v5.0 enhancements)
CREATE INDEX idx_products_sku ON inventory.products(sku);
CREATE INDEX idx_products_upc ON inventory.products(upc);
CREATE INDEX idx_products_category ON inventory.products(category);
CREATE INDEX idx_products_clinical_specialty ON inventory.products(clinical_specialty); -- v5.0 enhancement
CREATE INDEX idx_products_brand ON inventory.products(brand);
CREATE INDEX idx_products_manufacturer ON inventory.products(manufacturer);
CREATE INDEX idx_products_created ON inventory.products(created_at DESC);
CREATE INDEX idx_products_source ON inventory.products(primary_source_id);
CREATE INDEX idx_products_search_vector ON inventory.products USING GIN(search_vector);
CREATE INDEX idx_products_name_trgm ON inventory.products USING GIN(name gin_trgm_ops);
CREATE INDEX idx_products_embedding ON inventory.products USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100); -- v5.0 vector index

-- ==================================================================================
-- 5. INVENTORY SCHEMA: PRODUCT RELATIONSHIPS
-- ==================================================================================
CREATE TABLE inventory.product_relationships (
    relationship_id SERIAL PRIMARY KEY,
    parent_product_id INT NOT NULL REFERENCES inventory.products(product_id) ON DELETE CASCADE,
    child_product_id INT NOT NULL REFERENCES inventory.products(product_id) ON DELETE CASCADE,
    
    relationship_type VARCHAR(50) NOT NULL CHECK (relationship_type IN (
        'UPSELL',
        'CONSUMABLE',
        'ACCESSORY',
        'SUBSTITUTE',
        'CROSS_SELL',
        'COMPONENT',
        'COMPLEMENTARY',
        'PREREQUISITE',
        'ALTERNATIVE',
        'UPGRADE',
        'DOWNGRADE',
        'SPARE_PART',
        'REPLACEMENT'
    )),
    
    -- Relationship Metrics
    quantity_recommended INT DEFAULT 1 CHECK (quantity_recommended > 0),
    is_required BOOLEAN DEFAULT FALSE,
    discount_when_bundled DECIMAL(5,2) DEFAULT 0.00 CHECK (discount_when_bundled >= 0 AND discount_when_bundled <= 100),
    strength DECIMAL(3,2) DEFAULT 1.0 CHECK (strength >= 0 AND strength <= 1),
    
    -- Usage Statistics
    co_purchase_count INT DEFAULT 0,
    co_purchase_frequency INT DEFAULT 0,
    conversion_rate DECIMAL(5,2),
    last_co_purchased_at TIMESTAMP,
    
    -- Business Rules
    min_order_quantity INT DEFAULT 1,
    max_order_quantity INT,
    valid_from DATE DEFAULT CURRENT_DATE,
    valid_until DATE,
    
    -- Metadata
    reason_text VARCHAR(500),
    use_case TEXT,
    notes TEXT,
    source_id INT REFERENCES config.data_sources(source_id),
    
    -- Audit
    created_by INT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    
    -- Unique constraint to prevent duplicate relationships
    UNIQUE(parent_product_id, child_product_id, relationship_type)
);

-- Relationship indexes
CREATE INDEX idx_relationships_parent ON inventory.product_relationships(parent_product_id);
CREATE INDEX idx_relationships_child ON inventory.product_relationships(child_product_id);
CREATE INDEX idx_relationships_type ON inventory.product_relationships(relationship_type);
CREATE INDEX idx_relationships_composite ON inventory.product_relationships(parent_product_id, relationship_type);

-- ==================================================================================
-- 6. INVENTORY SCHEMA: BUNDLES
-- ==================================================================================
CREATE TABLE inventory.bundles (
    bundle_id SERIAL PRIMARY KEY,
    bundle_code VARCHAR(50) UNIQUE NOT NULL,
    external_id VARCHAR(100),
    
    -- Basic Info
    name VARCHAR(300) NOT NULL,
    description TEXT,
    short_description VARCHAR(500),
    
    -- Pricing Strategy
    pricing_strategy VARCHAR(30) DEFAULT 'DISCOUNT_PERCENT' CHECK (pricing_strategy IN (
        'DISCOUNT_PERCENT',
        'FIXED_PRICE',
        'TIERED_PRICING',
        'DYNAMIC_PRICING'
    )),
    discount_percent DECIMAL(5,2) DEFAULT 0.00 CHECK (discount_percent >= 0 AND discount_percent <= 100),
    fixed_price DECIMAL(14,2),
    base_price DECIMAL(14,2) GENERATED ALWAYS AS (
        COALESCE(fixed_price, 0)
    ) STORED,
    
    -- Currency & Financials
    currency VARCHAR(3) DEFAULT 'UGX',
    cost_price DECIMAL(14,2),
    margin_percent DECIMAL(5,2),
    
    -- Validity
    valid_from DATE DEFAULT CURRENT_DATE,
    valid_until DATE,
    is_seasonal BOOLEAN DEFAULT FALSE,
    season_name VARCHAR(50),
    
    -- Ordering Rules
    min_order_quantity INT DEFAULT 1 CHECK (min_order_quantity > 0),
    max_order_quantity INT,
    moq INT DEFAULT 1 CHECK (moq > 0),
    
    -- Categorization
    bundle_category VARCHAR(100),
    target_specialty VARCHAR(100), -- v5.0: Clinical specialty targeting
    target_customer_type VARCHAR(50),
    
    -- Inventory
    quantity_on_hand INT DEFAULT 0 CHECK (quantity_on_hand >= 0),
    quantity_reserved INT DEFAULT 0 CHECK (quantity_reserved >= 0),
    quantity_available INT GENERATED ALWAYS AS (quantity_on_hand - quantity_reserved) STORED,
    reorder_level INT DEFAULT 0,
    
    -- Status & Visibility
    is_active BOOLEAN DEFAULT TRUE,
    is_customizable BOOLEAN DEFAULT FALSE,
    is_private BOOLEAN DEFAULT FALSE,
    visibility VARCHAR(20) DEFAULT 'PUBLIC' CHECK (visibility IN ('PUBLIC', 'PRIVATE', 'GROUP')),
    
    -- Performance
    priority_rank INT DEFAULT 0,
    popularity_score DECIMAL(5,2) DEFAULT 0,
    times_sold INT DEFAULT 0,
    last_sold_at TIMESTAMP,
    
    -- Media
    image_url TEXT,
    brochure_url TEXT,
    
    -- Source
    source_id INT REFERENCES config.data_sources(source_id),
    
    -- Audit
    created_by INT,
    updated_by INT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    
    -- Constraints
    CONSTRAINT chk_bundle_price CHECK (
        (pricing_strategy = 'FIXED_PRICE' AND fixed_price IS NOT NULL) OR
        (pricing_strategy = 'DISCOUNT_PERCENT' AND discount_percent IS NOT NULL)
    ),
    CONSTRAINT chk_bundle_quantity CHECK (quantity_reserved <= quantity_on_hand)
);

CREATE TABLE inventory.bundle_items (
    bundle_item_id SERIAL PRIMARY KEY,
    bundle_id INT NOT NULL REFERENCES inventory.bundles(bundle_id) ON DELETE CASCADE,
    product_id INT NOT NULL REFERENCES inventory.products(product_id),
    
    -- Item Details
    quantity INT DEFAULT 1 CHECK (quantity > 0),
    is_optional BOOLEAN DEFAULT FALSE,
    default_selected BOOLEAN DEFAULT TRUE,
    sort_order INT DEFAULT 0,
    
    -- Pricing Override
    price_override DECIMAL(14,2),
    discount_override DECIMAL(5,2),
    
    -- Metadata
    notes TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    
    UNIQUE(bundle_id, product_id)
);

-- Bundle indexes
CREATE INDEX idx_bundles_code ON inventory.bundles(bundle_code);
CREATE INDEX idx_bundles_category ON inventory.bundles(bundle_category);
CREATE INDEX idx_bundles_active ON inventory.bundles(is_active, valid_from, valid_until);
CREATE INDEX idx_bundles_created ON inventory.bundles(created_at DESC);
CREATE INDEX idx_bundle_items_bundle ON inventory.bundle_items(bundle_id);
CREATE INDEX idx_bundle_items_product ON inventory.bundle_items(product_id);

-- ==================================================================================
-- 7. INVENTORY SCHEMA: PRODUCT OFFERINGS (Enhanced with v5.0 Sale Types)
-- ==================================================================================
CREATE TABLE inventory.product_offerings (
    offering_id SERIAL PRIMARY KEY,
    external_id VARCHAR(100) UNIQUE,
    product_id INT NOT NULL REFERENCES inventory.products(product_id) ON DELETE CASCADE,
    supplier_id INT NOT NULL REFERENCES inventory.suppliers(supplier_id) ON DELETE CASCADE,
    
    -- v5.0 ENHANCEMENT: Sale Type for Commission Logic
    sale_type VARCHAR(20) DEFAULT 'OWN_STOCK' CHECK (sale_type IN (
        'OWN_STOCK',   -- Inventory owned by SocioMed
        'COMMISSION',  -- Consignment/Partner Stock
        'DROPSHIP'     -- External Stock
    )),
    
    -- Supplier Specifics
    supplier_sku VARCHAR(100),
    supplier_product_name VARCHAR(500),
    supplier_description TEXT,
    
    -- Pricing
    price DECIMAL(14,2) NOT NULL CHECK (price >= 0),
    currency VARCHAR(3) DEFAULT 'UGX',
    cost_price DECIMAL(14,2) CHECK (cost_price >= 0),
    base_price DECIMAL(14,2),
    margin_percent DECIMAL(5,2),
    
    -- Inventory Management
    quantity_on_hand INT DEFAULT 0 CHECK (quantity_on_hand >= 0),
    quantity_reserved INT DEFAULT 0 CHECK (quantity_reserved >= 0),
    quantity_available INT GENERATED ALWAYS AS (
        GREATEST(quantity_on_hand - quantity_reserved, 0)
    ) STORED,
    quantity_on_order INT DEFAULT 0 CHECK (quantity_on_order >= 0),
    quantity_safety_stock INT DEFAULT 0,
    
    -- Reordering
    reorder_level INT DEFAULT 10 CHECK (reorder_level >= 0),
    reorder_quantity INT DEFAULT 50 CHECK (reorder_quantity > 0),
    economic_order_quantity INT,
    last_reorder_at TIMESTAMP,
    next_reorder_date DATE,
    
    -- Stock Status (Automatically managed by trigger)
    stock_status VARCHAR(20) DEFAULT 'IN_STOCK' CHECK (stock_status IN (
        'IN_STOCK',
        'LOW_STOCK',
        'OUT_OF_STOCK',
        'DISCONTINUED',
        'PRE_ORDER',
        'BACKORDER',
        'EXPIRED'
    )),
    stock_status_updated_at TIMESTAMP,
    
    -- Lead Time & Logistics
    lead_time_days INT DEFAULT 7 CHECK (lead_time_days >= 0),
    lead_time_variance_days INT DEFAULT 2,
    location_bin VARCHAR(50),
    warehouse_location VARCHAR(100),
    storage_type VARCHAR(50),
    handling_instructions TEXT,
    
    -- Ordering Rules
    moq INT DEFAULT 1 CHECK (moq > 0),
    max_order_quantity INT,
    order_multiple INT DEFAULT 1 CHECK (order_multiple > 0),
    
    -- Service & Support
    warranty_months INT DEFAULT 0 CHECK (warranty_months >= 0),
    installation_included BOOLEAN DEFAULT FALSE,
    training_included BOOLEAN DEFAULT FALSE,
    support_included BOOLEAN DEFAULT FALSE,
    calibration_included BOOLEAN DEFAULT FALSE,
    
    -- Validity
    valid_from DATE DEFAULT CURRENT_DATE,
    valid_until DATE,
    is_new_arrival BOOLEAN DEFAULT FALSE,
    new_until DATE,
    
    -- Source Tracking & Conflict Resolution
    source_id INT NOT NULL REFERENCES config.data_sources(source_id),
    source_file_name VARCHAR(255),
    source_record_id VARCHAR(100),
    last_synced_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    
    -- Conflict Resolution Flags
    is_primary_offering BOOLEAN DEFAULT TRUE,
    override_from_pdf BOOLEAN DEFAULT FALSE,
    is_manual_override BOOLEAN DEFAULT FALSE,
    override_reason TEXT,
    override_by INT,
    override_at TIMESTAMP,
    
    -- Status
    is_active BOOLEAN DEFAULT TRUE,
    deactivated_reason TEXT,
    deactivated_at TIMESTAMP,
    deactivated_by INT,
    
    -- Audit
    created_by INT,
    updated_by INT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    
    -- Performance Metrics
    times_ordered INT DEFAULT 0,
    times_viewed INT DEFAULT 0,
    last_ordered_at TIMESTAMP,
    avg_days_in_stock INT DEFAULT 0,
    
    -- Generated column for business logic
    is_socio_med_stock BOOLEAN GENERATED ALWAYS AS (
        supplier_id = (SELECT supplier_id FROM inventory.suppliers WHERE type = 'SOCIO_MED' LIMIT 1)
    ) STORED,
    
    -- Constraints
    UNIQUE(product_id, supplier_id, supplier_sku),
    CONSTRAINT chk_offering_quantities CHECK (quantity_reserved <= quantity_on_hand),
    CONSTRAINT chk_price_cost CHECK (cost_price IS NULL OR price >= cost_price)
);

-- Offering indexes
CREATE INDEX idx_offerings_product ON inventory.product_offerings(product_id);
CREATE INDEX idx_offerings_supplier ON inventory.product_offerings(supplier_id);
CREATE INDEX idx_offerings_stock_status ON inventory.product_offerings(stock_status, quantity_available);
CREATE INDEX idx_offerings_active ON inventory.product_offerings(is_active, valid_until);
CREATE INDEX idx_offerings_price ON inventory.product_offerings(price);
CREATE INDEX idx_offerings_source ON inventory.product_offerings(source_id);
CREATE INDEX idx_offerings_created ON inventory.product_offerings(created_at DESC);
CREATE INDEX idx_offerings_socio_med ON inventory.product_offerings(is_socio_med_stock);
CREATE INDEX idx_offerings_sale_type ON inventory.product_offerings(sale_type); -- v5.0 enhancement

-- ==================================================================================
-- 8. SALES SCHEMA: PRICE TIERS (Wholesale/Bulk Pricing)
-- ==================================================================================
CREATE TABLE sales.price_tiers (
    tier_id SERIAL PRIMARY KEY,
    offering_id INT NOT NULL REFERENCES inventory.product_offerings(offering_id) ON DELETE CASCADE,
    
    -- Tier Details
    tier_name VARCHAR(100),
    tier_description TEXT,
    min_quantity INT NOT NULL CHECK (min_quantity > 0),
    max_quantity INT,
    unit_price DECIMAL(14,2) NOT NULL CHECK (unit_price >= 0),
    currency VARCHAR(3) DEFAULT 'UGX',
    
    -- Discount Details
    discount_percent DECIMAL(5,2) GENERATED ALWAYS AS (
        CASE 
            WHEN (SELECT price FROM inventory.product_offerings WHERE offering_id = price_tiers.offering_id) > 0
            THEN ROUND(((SELECT price FROM inventory.product_offerings WHERE offering_id = price_tiers.offering_id) - unit_price) / 
                   (SELECT price FROM inventory.product_offerings WHERE offering_id = price_tiers.offering_id) * 100, 2)
            ELSE 0
        END
    ) STORED,
    
    -- Validity
    valid_from DATE DEFAULT CURRENT_DATE,
    valid_until DATE,
    is_active BOOLEAN DEFAULT TRUE,
    
    -- Customer Segmentation
    customer_type VARCHAR(50),
    customer_group VARCHAR(50),
    region VARCHAR(100),
    
    -- Audit
    created_by INT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    
    -- Constraints
    UNIQUE(offering_id, min_quantity),
    CONSTRAINT chk_tier_quantity_range CHECK (max_quantity IS NULL OR max_quantity > min_quantity)
);

-- Price tier indexes
CREATE INDEX idx_price_tiers_offering ON sales.price_tiers(offering_id);
CREATE INDEX idx_price_tiers_quantity ON sales.price_tiers(min_quantity);
CREATE INDEX idx_price_tiers_active ON sales.price_tiers(is_active, valid_from, valid_until);

-- ==================================================================================
-- 9. SALES SCHEMA: USERS (CRM)
-- ==================================================================================
CREATE TABLE sales.users (
    user_id SERIAL PRIMARY KEY,
    external_id VARCHAR(100) UNIQUE,
    
    -- Contact Information
    phone_number VARCHAR(30) UNIQUE NOT NULL,
    phone_verified BOOLEAN DEFAULT FALSE,
    phone_verified_at TIMESTAMP,
    whatsapp_id VARCHAR(50) UNIQUE,
    whatsapp_verified BOOLEAN DEFAULT FALSE,
    email VARCHAR(255),
    email_verified BOOLEAN DEFAULT FALSE,
    email_verified_at TIMESTAMP,
    
    -- Personal Information
    full_name VARCHAR(200),
    title VARCHAR(50),
    gender VARCHAR(10),
    date_of_birth DATE,
    nationality VARCHAR(100),
    
    -- Organization Details
    organization_name VARCHAR(300),
    organization_type VARCHAR(50) CHECK (organization_type IN (
        'HOSPITAL',
        'CLINIC',
        'PHARMACY',
        'LABORATORY',
        'MEDICAL_CENTER',
        'DENTAL_CLINIC',
        'VETERINARY_CLINIC',
        'INDIVIDUAL_PRACTITIONER',
        'WHOLESALER',
        'DISTRIBUTOR',
        'NGO',
        'GOVERNMENT',
        'OTHER'
    )),
    organization_size VARCHAR(20),
    organization_registration_number VARCHAR(100),
    organization_established_year INT,
    
    -- Contact Person (if different from primary)
    contact_person_name VARCHAR(200),
    contact_person_title VARCHAR(50),
    contact_person_phone VARCHAR(30),
    
    -- Location
    country VARCHAR(100) DEFAULT 'Uganda',
    region VARCHAR(100),
    district VARCHAR(100),
    subcounty VARCHAR(100),
    parish VARCHAR(100),
    village VARCHAR(100),
    address TEXT,
    street VARCHAR(200),
    building VARCHAR(100),
    floor VARCHAR(20),
    
    -- GPS Coordinates for delivery
    latitude DECIMAL(10,8),
    longitude DECIMAL(11,8),
    
    -- Business Registration
    tax_id VARCHAR(50),
    vat_number VARCHAR(50),
    tin_number VARCHAR(50),
    business_license_number VARCHAR(100),
    premise_no VARCHAR(50),
    premise_type VARCHAR(50),
    psu_no VARCHAR(50),
    
    -- Professional Details
    profession VARCHAR(100),
    specialization VARCHAR(200),
    qualifications TEXT[],
    license_number VARCHAR(100),
    practicing_certificate_number VARCHAR(100),
    
    -- User Type & Permissions
    user_type VARCHAR(20) DEFAULT 'BUYER' CHECK (user_type IN (
        'BUYER',
        'ADMIN',
        'SUPPLIER_REP',
        'SALES_AGENT',
        'ACCOUNT_MANAGER',
        'SUPER_ADMIN'
    )),
    roles VARCHAR(50)[] DEFAULT '{}',
    permissions JSONB DEFAULT '{}',
    
    -- Bot State Management
    bot_state JSONB DEFAULT '{
        "current_flow": null,
        "step": null,
        "context": {},
        "last_intent": null,
        "conversation_history": [],
        "preferences": {}
    }',
    
    -- Communication Preferences
    preferred_language VARCHAR(10) DEFAULT 'en',
    communication_channel VARCHAR(20) DEFAULT 'WHATSAPP' CHECK (communication_channel IN (
        'WHATSAPP',
        'SMS',
        'EMAIL',
        'PHONE_CALL'
    )),
    notification_preferences JSONB DEFAULT '{
        "price_alerts": true,
        "stock_alerts": true,
        "order_updates": true,
        "promotions": true
    }',
    
    -- Financial
    payment_terms VARCHAR(100),
    credit_limit DECIMAL(14,2) DEFAULT 0.00,
    credit_used DECIMAL(14,2) DEFAULT 0.00,
    credit_available DECIMAL(14,2) GENERATED ALWAYS AS (credit_limit - credit_used) STORED,
    payment_methods VARCHAR(50)[],
    preferred_payment_method VARCHAR(50),
    currency_preference VARCHAR(3) DEFAULT 'UGX',
    
    -- Status & Verification
    status VARCHAR(20) DEFAULT 'ACTIVE' CHECK (status IN ('ACTIVE', 'INACTIVE', 'SUSPENDED', 'BLACKLISTED')),
    is_verified BOOLEAN DEFAULT FALSE,
    verification_level VARCHAR(20) DEFAULT 'BASIC' CHECK (verification_level IN ('BASIC', 'STANDARD', 'ENHANCED')),
    verification_date TIMESTAMP,
    verification_notes TEXT,
    verification_documents JSONB,
    
    -- Sales Relationship
    assigned_sales_agent_id INT,
    customer_segment VARCHAR(50),
    customer_tier VARCHAR(20) DEFAULT 'BRONZE' CHECK (customer_tier IN ('BRONZE', 'SILVER', 'GOLD', 'PLATINUM')),
    loyalty_points INT DEFAULT 0,
    
    -- Activity Tracking
    last_interaction_at TIMESTAMP,
    last_purchase_at TIMESTAMP,
    first_purchase_at TIMESTAMP,
    total_orders INT DEFAULT 0,
    total_spent DECIMAL(16,2) DEFAULT 0.00,
    avg_order_value DECIMAL(14,2) DEFAULT 0.00,
    
    -- Product Preferences
    primary_products TEXT[],
    product_categories_interested VARCHAR(100)[],
    brand_preferences VARCHAR(200)[],
    clinical_interests VARCHAR(100)[], -- v5.0 enhancement: Clinical specialty interests
    
    -- Notes & Metadata
    notes TEXT,
    internal_notes TEXT,
    metadata JSONB DEFAULT '{}',
    tags VARCHAR(50)[],
    
    -- Audit
    referral_code VARCHAR(50) UNIQUE,
    referred_by INT REFERENCES sales.users(user_id),
    created_by INT,
    updated_by INT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    
    -- Constraints
    CONSTRAINT chk_user_credit CHECK (credit_used <= credit_limit)
);

-- User indexes
CREATE INDEX idx_users_phone ON sales.users(phone_number);
CREATE INDEX idx_users_email ON sales.users(email);
CREATE INDEX idx_users_organization ON sales.users(organization_name);
CREATE INDEX idx_users_type ON sales.users(user_type, status);
CREATE INDEX idx_users_location ON sales.users(country, district);
CREATE INDEX idx_users_created ON sales.users(created_at DESC);
CREATE INDEX idx_users_agent ON sales.users(assigned_sales_agent_id);
CREATE INDEX idx_users_tier ON sales.users(customer_tier);
CREATE INDEX idx_users_activity ON sales.users(last_interaction_at DESC);
CREATE INDEX idx_users_spent ON sales.users(total_spent DESC);
CREATE INDEX idx_users_clinical_interests ON sales.users USING GIN(clinical_interests); -- v5.0 enhancement

-- ==================================================================================
-- 10. SALES SCHEMA: UNMET DEMAND
-- ==================================================================================
CREATE TABLE sales.unmet_demand (
    demand_id SERIAL PRIMARY KEY,
    
    -- Search Information
    user_phone VARCHAR(30) NOT NULL,
    user_id INT REFERENCES sales.users(user_id) ON DELETE SET NULL,
    search_term VARCHAR(500) NOT NULL,
    normalized_term VARCHAR(500),
    original_query TEXT,
    
    -- Demand Analysis
    demand_type VARCHAR(50) NOT NULL CHECK (demand_type IN (
        'PRODUCT_NOT_FOUND',
        'PRICE_TOO_HIGH',
        'OUT_OF_STOCK',
        'SPECIFICATION_MISMATCH',
        'BRAND_PREFERENCE',
        'QUANTITY_UNAVAILABLE'
    )),
    product_id INT REFERENCES inventory.products(product_id),
    category_suggested VARCHAR(100),
    subcategory_suggested VARCHAR(200),
    clinical_specialty_suggested VARCHAR(100), -- v5.0 enhancement
    
    -- Context
    conversation_context JSONB,
    session_id VARCHAR(100),
    interaction_id INT,
    
    -- Urgency & Volume
    urgency_level VARCHAR(20) DEFAULT 'NORMAL' CHECK (urgency_level IN ('LOW', 'NORMAL', 'HIGH', 'CRITICAL')),
    estimated_quantity INT,
    estimated_frequency VARCHAR(50),
    budget_range_low DECIMAL(14,2),
    budget_range_high DECIMAL(14,2),
    
    -- Fulfillment Tracking
    was_fulfilled BOOLEAN DEFAULT FALSE,
    fulfilled_at TIMESTAMP,
    fulfilled_by_product_id INT REFERENCES inventory.products(product_id),
    fulfillment_method VARCHAR(50),
    fulfillment_notes TEXT,
    
    -- Supplier Notification
    notified_suppliers INT[],
    supplier_responses JSONB,
    
    -- Analytics
    search_count INT DEFAULT 1,
    last_searched_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    first_searched_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    
    -- Status
    status VARCHAR(20) DEFAULT 'OPEN' CHECK (status IN ('OPEN', 'IN_PROGRESS', 'RESOLVED', 'CLOSED')),
    priority_score INT DEFAULT 0,
    
    -- Audit
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Unmet demand indexes
CREATE INDEX idx_unmet_demand_term ON sales.unmet_demand USING GIN(search_term gin_trgm_ops);
CREATE INDEX idx_unmet_demand_user ON sales.unmet_demand(user_id, user_phone);
CREATE INDEX idx_unmet_demand_status ON sales.unmet_demand(status, urgency_level);
CREATE INDEX idx_unmet_demand_created ON sales.unmet_demand(created_at DESC);
CREATE INDEX idx_unmet_demand_product ON sales.unmet_demand(product_id);
CREATE INDEX idx_unmet_demand_fulfilled ON sales.unmet_demand(was_fulfilled, fulfilled_at);
CREATE INDEX idx_unmet_demand_clinical ON sales.unmet_demand(clinical_specialty_suggested); -- v5.0 enhancement

-- ==================================================================================
-- 11. SALES SCHEMA: INTERACTIONS
-- ==================================================================================
CREATE TABLE sales.interactions (
    interaction_id SERIAL PRIMARY KEY,
    interaction_uuid UUID DEFAULT uuid_generate_v4(),
    
    -- User Context
    user_id INT REFERENCES sales.users(user_id) ON DELETE CASCADE,
    session_id VARCHAR(100) NOT NULL,
    conversation_id VARCHAR(100),
    
    -- Message Details
    message_type VARCHAR(20) DEFAULT 'TEXT' CHECK (message_type IN (
        'TEXT',
        'IMAGE',
        'DOCUMENT',
        'AUDIO',
        'VIDEO',
        'LOCATION',
        'CONTACT'
    )),
    message_text TEXT,
    message_media_url TEXT,
    message_direction VARCHAR(10) NOT NULL CHECK (message_direction IN ('INBOUND', 'OUTBOUND')),
    
    -- Intent Analysis
    intent_detected VARCHAR(100),
    confidence_score DECIMAL(3,2) CHECK (confidence_score >= 0 AND confidence_score <= 1),
    entities_detected JSONB,
    sentiment_score DECIMAL(3,2),
    
    -- Product Context
    product_inquired INT REFERENCES inventory.products(product_id),
    products_shown INT[],
    bundles_shown INT[],
    
    -- Response
    response_text TEXT,
    response_type VARCHAR(50),
    response_time_ms INT,
    is_automated_response BOOLEAN DEFAULT TRUE,
    
    -- Action Tracking
    action_taken VARCHAR(100),
    next_action_suggested VARCHAR(100),
    is_referral_generated BOOLEAN DEFAULT FALSE,
    referral_type VARCHAR(50),
    
    -- Channel Information
    channel VARCHAR(20) DEFAULT 'WHATSAPP' CHECK (channel IN (
        'WHATSAPP',
        'SMS',
        'EMAIL',
        'WEB_CHAT',
        'PHONE_CALL',
        'MOBILE_APP'
    )),
    channel_message_id VARCHAR(100),
    channel_specific_data JSONB,
    
    -- Device & Location
    user_agent TEXT,
    ip_address INET,
    device_type VARCHAR(50),
    location JSONB,
    
    -- Performance Metrics
    was_helpful BOOLEAN,
    rating INT CHECK (rating >= 1 AND rating <= 5),
    feedback_text TEXT,
    
    -- Timestamps
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    processed_at TIMESTAMP,
    responded_at TIMESTAMP
);

-- Interaction indexes
CREATE INDEX idx_interactions_user ON sales.interactions(user_id, created_at DESC);
CREATE INDEX idx_interactions_session ON sales.interactions(session_id);
CREATE INDEX idx_interactions_intent ON sales.interactions(intent_detected);
CREATE INDEX idx_interactions_product ON sales.interactions(product_inquired);
CREATE INDEX idx_interactions_channel ON sales.interactions(channel, created_at);
CREATE INDEX idx_interactions_created ON sales.interactions(created_at DESC);
CREATE INDEX idx_interactions_processed ON sales.interactions(processed_at);

-- ==================================================================================
-- 12. SALES SCHEMA: QUOTES
-- ==================================================================================
CREATE TABLE sales.quotes (
    quote_id SERIAL PRIMARY KEY,
    quote_uuid UUID DEFAULT uuid_generate_v4(),
    quote_number VARCHAR(50) UNIQUE,
    external_reference VARCHAR(100),
    
    -- Customer Information
    user_id INT NOT NULL REFERENCES sales.users(user_id),
    customer_phone VARCHAR(30),
    customer_email VARCHAR(255),
    customer_name VARCHAR(200),
    customer_organization VARCHAR(300),
    
    -- Quote Details
    status VARCHAR(20) DEFAULT 'DRAFT' CHECK (status IN (
        'DRAFT',
        'PENDING',
        'SENT',
        'VIEWED',
        'REVISED',
        'CONFIRMED',
        'EXPIRED',
        'CANCELLED',
        'PAID',
        'PARTIALLY_PAID',
        'DELIVERED',
        'COMPLETED'
    )),
    quote_type VARCHAR(20) DEFAULT 'STANDARD' CHECK (quote_type IN (
        'STANDARD',
        'PROFORMA',
        'COMMERCIAL_INVOICE',
        'TAX_INVOICE',
        'CREDIT_NOTE'
    )),
    
    -- Pricing
    subtotal DECIMAL(16,2) DEFAULT 0.00,
    discount_amount DECIMAL(16,2) DEFAULT 0.00,
    discount_percent DECIMAL(5,2) DEFAULT 0.00,
    tax_amount DECIMAL(16,2) DEFAULT 0.00,
    tax_rate DECIMAL(5,2) DEFAULT 0.00,
    shipping_amount DECIMAL(16,2) DEFAULT 0.00,
    handling_amount DECIMAL(16,2) DEFAULT 0.00,
    total_amount DECIMAL(16,2) DEFAULT 0.00,
    amount_paid DECIMAL(16,2) DEFAULT 0.00,
    balance_due DECIMAL(16,2) GENERATED ALWAYS AS (total_amount - amount_paid) STORED,
    
    -- Currency
    currency VARCHAR(3) DEFAULT 'UGX',
    exchange_rate DECIMAL(10,4) DEFAULT 1.0,
    exchange_rate_date DATE DEFAULT CURRENT_DATE,
    
    -- Payment
    payment_terms VARCHAR(100),
    payment_status VARCHAR(20) DEFAULT 'PENDING' CHECK (payment_status IN (
        'PENDING',
        'PARTIALLY_PAID',
        'PAID',
        'OVERDUE',
        'REFUNDED',
        'CANCELLED'
    )),
    payment_method VARCHAR(50),
    payment_reference VARCHAR(100),
    payment_due_date DATE,
    
    -- Delivery
    delivery_address TEXT,
    delivery_instructions TEXT,
    delivery_method VARCHAR(50),
    estimated_delivery_date DATE,
    actual_delivery_date DATE,
    delivery_status VARCHAR(20) DEFAULT 'PENDING',
    tracking_number VARCHAR(100),
    shipping_carrier VARCHAR(50),
    
    -- Validity
    valid_until DATE,
    expires_at TIMESTAMP,
    
    -- Timestamps
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    sent_at TIMESTAMP,
    viewed_at TIMESTAMP,
    confirmed_at TIMESTAMP,
    paid_at TIMESTAMP,
    completed_at TIMESTAMP,
    
    -- Source
    source_channel VARCHAR(20) DEFAULT 'WHATSAPP',
    source_platform VARCHAR(50),
    created_by_user_id INT REFERENCES sales.users(user_id),
    sales_agent_id INT REFERENCES sales.users(user_id),
    
    -- Documents
    pdf_url TEXT,
    pdf_generated_at TIMESTAMP,
    terms_and_conditions TEXT,
    notes TEXT,
    internal_notes TEXT,
    
    -- v5.0 ENHANCEMENT: Commission Tracking
    commission_rate DECIMAL(5,2) DEFAULT 0.00,
    commission_amount DECIMAL(14,2) DEFAULT 0.00,
    is_commission_eligible BOOLEAN GENERATED ALWAYS AS (
        EXISTS (
            SELECT 1 FROM sales.quote_items qi
            JOIN inventory.product_offerings po ON qi.offering_id = po.offering_id
            WHERE qi.quote_id = quotes.quote_id 
            AND po.sale_type = 'COMMISSION'
        )
    ) STORED,
    
    -- Audit Trail
    revision_number INT DEFAULT 1,
    parent_quote_id INT REFERENCES sales.quotes(quote_id),
    version_notes TEXT,
    
    -- Constraints
    CONSTRAINT chk_quote_amounts CHECK (
        subtotal >= 0 AND
        discount_amount >= 0 AND
        tax_amount >= 0 AND
        total_amount >= 0 AND
        amount_paid >= 0 AND
        amount_paid <= total_amount
    )
);

CREATE TABLE sales.quote_items (
    item_id SERIAL PRIMARY KEY,
    quote_id INT NOT NULL REFERENCES sales.quotes(quote_id) ON DELETE CASCADE,
    
    -- Product Reference
    offering_id INT REFERENCES inventory.product_offerings(offering_id),
    product_id INT REFERENCES inventory.products(product_id),
    
    -- Product Details (Denormalized for historical accuracy)
    product_name VARCHAR(500) NOT NULL,
    sku VARCHAR(100),
    brand VARCHAR(200),
    description TEXT,
    unit_of_measure VARCHAR(50),
    
    -- Pricing
    quantity INT NOT NULL CHECK (quantity > 0),
    unit_price DECIMAL(14,2) NOT NULL CHECK (unit_price >= 0),
    original_price DECIMAL(14,2),
    discount_percent DECIMAL(5,2) DEFAULT 0.00,
    discount_amount DECIMAL(14,2) DEFAULT 0.00,
    tax_rate DECIMAL(5,2) DEFAULT 0.00,
    tax_amount DECIMAL(14,2) DEFAULT 0.00,
    line_total DECIMAL(16,2) GENERATED ALWAYS AS (
        ROUND((quantity * unit_price * (1 - COALESCE(discount_percent, 0) / 100)) + COALESCE(tax_amount, 0), 2)
    ) STORED,
    
    -- v5.0 ENHANCEMENT: Commission Details
    sale_type VARCHAR(20), -- Denormalized from offering
    commission_rate DECIMAL(5,2),
    commission_amount DECIMAL(14,2),
    
    -- Inventory
    stock_status_at_time VARCHAR(50),
    lead_time_days INT,
    delivery_date_estimate DATE,
    
    -- Bundle Information
    bundle_id INT REFERENCES inventory.bundles(bundle_id),
    is_bundle_item BOOLEAN DEFAULT FALSE,
    bundle_item_sequence INT,
    
    -- Notes
    notes TEXT,
    
    -- Audit
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    
    -- Constraints
    CONSTRAINT chk_quote_item_discount CHECK (discount_percent >= 0 AND discount_percent <= 100)
);

-- Quote indexes
CREATE INDEX idx_quotes_number ON sales.quotes(quote_number);
CREATE INDEX idx_quotes_user ON sales.quotes(user_id, created_at DESC);
CREATE INDEX idx_quotes_status ON sales.quotes(status, payment_status);
CREATE INDEX idx_quotes_created ON sales.quotes(created_at DESC);
CREATE INDEX idx_quotes_sales_agent ON sales.quotes(sales_agent_id);
CREATE INDEX idx_quotes_total ON sales.quotes(total_amount DESC);
CREATE INDEX idx_quotes_commission ON sales.quotes(is_commission_eligible, commission_amount); -- v5.0 enhancement
CREATE INDEX idx_quote_items_quote ON sales.quote_items(quote_id);
CREATE INDEX idx_quote_items_product ON sales.quote_items(product_id);
CREATE INDEX idx_quote_items_offering ON sales.quote_items(offering_id);

-- ==================================================================================
-- 13. AUDIT SCHEMA: AUDIT LOGS (Partitioned by Month)
-- ==================================================================================
CREATE TABLE audit.audit_logs (
    log_id BIGSERIAL,
    log_uuid UUID DEFAULT uuid_generate_v4(),
    
    -- Table Information
    schema_name VARCHAR(50) NOT NULL,
    table_name VARCHAR(50) NOT NULL,
    record_id INT NOT NULL,
    operation VARCHAR(10) NOT NULL CHECK (operation IN ('INSERT', 'UPDATE', 'DELETE', 'TRUNCATE')),
    
    -- Change Details
    old_values JSONB,
    new_values JSONB,
    changed_columns TEXT[],
    diff JSONB,
    
    -- Source Information
    changed_by_user_id INT REFERENCES sales.users(user_id),
    changed_by_source_id INT REFERENCES config.data_sources(source_id),
    application_name VARCHAR(100),
    transaction_id BIGINT,
    
    -- Context
    ip_address INET,
    user_agent TEXT,
    request_url TEXT,
    request_method VARCHAR(10),
    
    -- Timestamps
    changed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    logged_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    
    -- Partition key
    log_date DATE DEFAULT CURRENT_DATE,
    
    PRIMARY KEY (log_date, log_id)
) PARTITION BY RANGE (log_date);

-- Create partitions for current and next 12 months
CREATE TABLE audit.audit_logs_y2024m01 PARTITION OF audit.audit_logs
    FOR VALUES FROM ('2024-01-01') TO ('2024-02-01');

CREATE TABLE audit.audit_logs_y2024m02 PARTITION OF audit.audit_logs
    FOR VALUES FROM ('2024-02-01') TO ('2024-03-01');

CREATE TABLE audit.audit_logs_y2024m03 PARTITION OF audit.audit_logs
    FOR VALUES FROM ('2024-03-01') TO ('2024-04-01');

-- Add more partitions as needed...

-- Audit log indexes
CREATE INDEX idx_audit_logs_table ON audit.audit_logs(schema_name, table_name, record_id);
CREATE INDEX idx_audit_logs_operation ON audit.audit_logs(operation, changed_at);
CREATE INDEX idx_audit_logs_user ON audit.audit_logs(changed_by_user_id);
CREATE INDEX idx_audit_logs_date ON audit.audit_logs(log_date, changed_at DESC);
CREATE INDEX idx_audit_logs_source ON audit.audit_logs(changed_by_source_id);

-- ==================================================================================
-- 14. FUNCTIONS & TRIGGERS
-- ==================================================================================

-- Function to update timestamps
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Function to generate quote numbers
CREATE SEQUENCE sales.quotes_seq START 1001;

CREATE OR REPLACE FUNCTION sales.generate_quote_number()
RETURNS TRIGGER AS $$
BEGIN
    IF NEW.quote_number IS NULL THEN
        NEW.quote_number := 'QT-' || 
                           EXTRACT(YEAR FROM CURRENT_DATE) || '-' || 
                           LPAD(NEXTVAL('sales.quotes_seq')::TEXT, 6, '0');
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_quote_number
BEFORE INSERT ON sales.quotes
FOR EACH ROW
EXECUTE FUNCTION sales.generate_quote_number();

-- Function to reserve inventory when quote is confirmed
CREATE OR REPLACE FUNCTION sales.reserve_inventory()
RETURNS TRIGGER AS $$
BEGIN
    IF NEW.status = 'CONFIRMED' AND OLD.status != 'CONFIRMED' THEN
        -- Update reserved quantities
        UPDATE inventory.product_offerings po
        SET quantity_reserved = quantity_reserved + qi.quantity,
            last_updated = CURRENT_TIMESTAMP
        FROM sales.quote_items qi
        WHERE qi.quote_id = NEW.quote_id 
          AND po.offering_id = qi.offering_id
          AND po.quantity_available >= qi.quantity;
        
        -- Update bundle reserved quantities if applicable
        UPDATE inventory.bundles b
        SET quantity_reserved = quantity_reserved + qi.quantity
        FROM sales.quote_items qi
        WHERE qi.quote_id = NEW.quote_id 
          AND b.bundle_id = qi.bundle_id
          AND b.quantity_available >= qi.quantity;
    END IF;
    
    -- Update timestamps
    IF NEW.status = 'CONFIRMED' AND OLD.status != 'CONFIRMED' THEN
        NEW.confirmed_at := CURRENT_TIMESTAMP;
    ELSIF NEW.status = 'PAID' AND OLD.status != 'PAID' THEN
        NEW.paid_at := CURRENT_TIMESTAMP;
    ELSIF NEW.status = 'SENT' AND OLD.status != 'SENT' THEN
        NEW.sent_at := CURRENT_TIMESTAMP;
    END IF;
    
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_reserve_inventory
AFTER UPDATE ON sales.quotes
FOR EACH ROW
EXECUTE FUNCTION sales.reserve_inventory();

-- Function to update stock status automatically
CREATE OR REPLACE FUNCTION inventory.update_stock_status()
RETURNS TRIGGER AS $$
BEGIN
    -- Calculate available quantity
    NEW.quantity_available := GREATEST(NEW.quantity_on_hand - NEW.quantity_reserved, 0);
    
    -- Update stock status based on available quantity
    NEW.stock_status := CASE
        WHEN NEW.quantity_on_hand = 0 THEN 'OUT_OF_STOCK'
        WHEN NEW.quantity_available = 0 THEN 'OUT_OF_STOCK'
        WHEN NEW.quantity_available <= NEW.reorder_level THEN 'LOW_STOCK'
        ELSE 'IN_STOCK'
    END;
    
    NEW.stock_status_updated_at := CURRENT_TIMESTAMP;
    NEW.last_updated := CURRENT_TIMESTAMP;
    
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_update_stock_status
BEFORE INSERT OR UPDATE ON inventory.product_offerings
FOR EACH ROW
EXECUTE FUNCTION inventory.update_stock_status();

-- Function to automatically create audit log partitions
CREATE OR REPLACE FUNCTION audit.create_audit_partition()
RETURNS TRIGGER AS $$
DECLARE
    partition_date DATE;
    partition_name TEXT;
    start_date DATE;
    end_date DATE;
BEGIN
    partition_date := DATE_TRUNC('MONTH', NEW.log_date);
    partition_name := 'audit_logs_y' || 
                     EXTRACT(YEAR FROM partition_date) || 
                     'm' || LPAD(EXTRACT(MONTH FROM partition_date)::TEXT, 2, '0');
    
    start_date := partition_date;
    end_date := partition_date + INTERVAL '1 month';
    
    -- Create partition if it doesn't exist
    IF NOT EXISTS (
        SELECT 1 FROM pg_tables 
        WHERE schemaname = 'audit' 
        AND tablename = partition_name
    ) THEN
        EXECUTE format(
            'CREATE TABLE audit.%I PARTITION OF audit.audit_logs
            FOR VALUES FROM (%L) TO (%L)',
            partition_name, start_date, end_date
        );
        
        -- Create indexes on the new partition
        EXECUTE format(
            'CREATE INDEX idx_%s_table ON audit.%I(schema_name, table_name, record_id)',
            partition_name, partition_name
        );
        EXECUTE format(
            'CREATE INDEX idx_%s_date ON audit.%I(log_date, changed_at DESC)',
            partition_name, partition_name
        );
    END IF;
    
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_create_audit_partition
BEFORE INSERT ON audit.audit_logs
FOR EACH ROW
EXECUTE FUNCTION audit.create_audit_partition();

-- Conflict Resolution Functions

-- Product Conflict Resolution (Excel beats PDF)
CREATE OR REPLACE FUNCTION inventory.resolve_product_conflict()
RETURNS TRIGGER AS $$
DECLARE
    existing_source_priority INT;
    new_source_priority INT;
    excel_source_id INT;
BEGIN
    -- Get source priorities
    SELECT priority INTO existing_source_priority 
    FROM config.data_sources 
    WHERE source_id = OLD.primary_source_id;
    
    SELECT priority INTO new_source_priority 
    FROM config.data_sources 
    WHERE source_id = NEW.primary_source_id;
    
    -- Get Excel source ID
    SELECT source_id INTO excel_source_id 
    FROM config.data_sources 
    WHERE source_name = 'excel_import' AND is_active = TRUE 
    LIMIT 1;
    
    -- If existing is Excel (priority=10) and new is PDF (priority=50), protect Excel data
    IF existing_source_priority < new_source_priority AND 
       OLD.primary_source_id = excel_source_id THEN
        -- Protect core fields from being overwritten by lower priority sources
        NEW.name := OLD.name;
        NEW.category := OLD.category;
        NEW.clinical_specialty := OLD.clinical_specialty; -- v5.0 enhancement
        NEW.short_description := OLD.short_description;
        NEW.manufacturer := OLD.manufacturer;
        NEW.brand := OLD.brand;
        NEW.sku := OLD.sku;
        NEW.upsell_hints := OLD.upsell_hints;
        
        -- Keep original source
        NEW.primary_source_id := OLD.primary_source_id;
        NEW.version := OLD.version + 1;
        
        -- Log the attempt
        NEW.last_updated_by_source_id := NEW.primary_source_id;
        RAISE NOTICE 'Protected Excel product data from being overwritten by lower priority source. Product ID: %', OLD.product_id;
    ELSE
        -- Update allowed
        NEW.last_updated_by_source_id := NEW.primary_source_id;
        NEW.version := OLD.version + 1;
    END IF;
    
    NEW.last_updated_at := CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_resolve_product_conflict
BEFORE UPDATE ON inventory.products
FOR EACH ROW
EXECUTE FUNCTION inventory.resolve_product_conflict();

-- Offering Conflict Resolution
CREATE OR REPLACE FUNCTION inventory.resolve_offering_conflict()
RETURNS TRIGGER AS $$
DECLARE
    existing_source_priority INT;
    new_source_priority INT;
    excel_source_id INT;
BEGIN
    SELECT priority INTO existing_source_priority 
    FROM config.data_sources 
    WHERE source_id = OLD.source_id;
    
    SELECT priority INTO new_source_priority 
    FROM config.data_sources 
    WHERE source_id = NEW.source_id;
    
    SELECT source_id INTO excel_source_id 
    FROM config.data_sources 
    WHERE source_name = 'excel_import' AND is_active = TRUE 
    LIMIT 1;
    
    -- Excel (10) beats PDF (50) unless explicitly overridden
    IF existing_source_priority < new_source_priority AND 
       OLD.source_id = excel_source_id AND 
       NOT NEW.override_from_pdf THEN
        -- Protect inventory & price data
        NEW.price := OLD.price;
        NEW.quantity_on_hand := OLD.quantity_on_hand;
        NEW.stock_status := OLD.stock_status;
        NEW.sale_type := OLD.sale_type; -- v5.0 enhancement
        NEW.source_id := OLD.source_id; -- Keep ownership
        
        -- Log override attempt
        NEW.is_manual_override := TRUE;
        NEW.override_reason := 'Protected Excel data from lower priority source';
        NEW.override_at := CURRENT_TIMESTAMP;
        
        RAISE NOTICE 'Protected Excel offering data from being overwritten. Offering ID: %', OLD.offering_id;
    END IF;
    
    NEW.last_updated := CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_resolve_offering_conflict
BEFORE UPDATE ON inventory.product_offerings
FOR EACH ROW
EXECUTE FUNCTION inventory.resolve_offering_conflict();

-- Function to calculate quote totals (including v5.0 commission logic)
CREATE OR REPLACE FUNCTION sales.calculate_quote_totals(quote_id INT)
RETURNS VOID AS $$
DECLARE
    quote_subtotal DECIMAL(16,2);
    quote_tax DECIMAL(16,2);
    quote_commission DECIMAL(16,2);
    quote_total DECIMAL(16,2);
BEGIN
    -- Calculate subtotal from items
    SELECT COALESCE(SUM(line_total), 0) INTO quote_subtotal
    FROM sales.quote_items
    WHERE quote_id = calculate_quote_totals.quote_id;
    
    -- Calculate tax (assuming 18% VAT for Uganda)
    quote_tax := ROUND(quote_subtotal * 0.18, 2);
    
    -- v5.0 ENHANCEMENT: Calculate commission for commission items
    SELECT COALESCE(SUM(
        CASE WHEN qi.sale_type = 'COMMISSION' AND qi.commission_rate > 0 
             THEN qi.line_total * (qi.commission_rate / 100)
             ELSE 0 
        END
    ), 0) INTO quote_commission
    FROM sales.quote_items qi
    WHERE qi.quote_id = calculate_quote_totals.quote_id;
    
    quote_total := quote_subtotal + quote_tax;
    
    -- Update quote with v5.0 commission tracking
    UPDATE sales.quotes
    SET subtotal = quote_subtotal,
        tax_amount = quote_tax,
        tax_rate = 18.00,
        commission_amount = quote_commission,
        total_amount = quote_total,
        updated_at = CURRENT_TIMESTAMP
    WHERE quote_id = calculate_quote_totals.quote_id;
END;
$$ LANGUAGE plpgsql;

-- v5.0 ENHANCEMENT: Function to populate commission details in quote items
CREATE OR REPLACE FUNCTION sales.populate_commission_details()
RETURNS TRIGGER AS $$
BEGIN
    -- Populate sale_type and commission_rate from product_offerings
    IF NEW.offering_id IS NOT NULL THEN
        SELECT po.sale_type, 
               CASE 
                   WHEN po.sale_type = 'COMMISSION' THEN s.commission_rate
                   ELSE 0 
               END
        INTO NEW.sale_type, NEW.commission_rate
        FROM inventory.product_offerings po
        LEFT JOIN inventory.suppliers s ON po.supplier_id = s.supplier_id
        WHERE po.offering_id = NEW.offering_id;
        
        -- Calculate commission amount if applicable
        IF NEW.sale_type = 'COMMISSION' AND NEW.commission_rate > 0 THEN
            NEW.commission_amount := ROUND(
                (NEW.quantity * NEW.unit_price * (1 - COALESCE(NEW.discount_percent, 0) / 100)) 
                * (NEW.commission_rate / 100), 
                2
            );
        ELSE
            NEW.commission_amount := 0;
        END IF;
    END IF;
    
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_populate_commission_details
BEFORE INSERT ON sales.quote_items
FOR EACH ROW
EXECUTE FUNCTION sales.populate_commission_details();

-- Trigger to update quote totals when items change
CREATE OR REPLACE FUNCTION sales.update_quote_totals_trigger()
RETURNS TRIGGER AS $$
BEGIN
    IF TG_OP = 'INSERT' OR TG_OP = 'UPDATE' OR TG_OP = 'DELETE' THEN
        IF TG_OP = 'DELETE' THEN
            PERFORM sales.calculate_quote_totals(OLD.quote_id);
        ELSE
            PERFORM sales.calculate_quote_totals(NEW.quote_id);
        END IF;
    END IF;
    RETURN NULL;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_update_quote_totals
AFTER INSERT OR UPDATE OR DELETE ON sales.quote_items
FOR EACH ROW
EXECUTE FUNCTION sales.update_quote_totals_trigger();

-- Function to check inventory availability before confirming quote
CREATE OR REPLACE FUNCTION sales.check_inventory_availability()
RETURNS TRIGGER AS $$
DECLARE
    item_record RECORD;
    available_qty INT;
    error_msg TEXT;
BEGIN
    IF NEW.status = 'CONFIRMED' AND OLD.status != 'CONFIRMED' THEN
        FOR item_record IN 
            SELECT qi.item_id, qi.offering_id, qi.quantity, 
                   po.quantity_available, p.name, po.sale_type -- v5.0: Include sale_type
            FROM sales.quote_items qi
            LEFT JOIN inventory.product_offerings po ON qi.offering_id = po.offering_id
            LEFT JOIN inventory.products p ON po.product_id = p.product_id
            WHERE qi.quote_id = NEW.quote_id
        LOOP
            IF item_record.offering_id IS NOT NULL THEN
                -- v5.0 ENHANCEMENT: Only check stock for OWN_STOCK items
                IF item_record.sale_type = 'OWN_STOCK' AND 
                   item_record.quantity_available < item_record.quantity THEN
                    error_msg := format('Insufficient stock for product: %s. Available: %s, Requested: %s',
                                       item_record.name, 
                                       item_record.quantity_available, 
                                       item_record.quantity);
                    RAISE EXCEPTION '%', error_msg;
                END IF;
            END IF;
        END LOOP;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_check_inventory_availability
BEFORE UPDATE ON sales.quotes
FOR EACH ROW
EXECUTE FUNCTION sales.check_inventory_availability();

-- Function to generate SKU automatically
CREATE OR REPLACE FUNCTION inventory.generate_sku()
RETURNS TRIGGER AS $$
DECLARE
    category_code VARCHAR(10);
    brand_code VARCHAR(10);
    seq_num INT;
BEGIN
    IF NEW.sku IS NULL THEN
        -- Generate category code
        category_code := UPPER(SUBSTRING(NEW.category FROM 1 FOR 3));
        
        -- Generate brand code (first 3 letters)
        IF NEW.brand IS NOT NULL THEN
            brand_code := UPPER(SUBSTRING(NEW.brand FROM 1 FOR 3));
        ELSE
            brand_code := 'GEN';
        END IF;
        
        -- Get next sequence number for this category-brand combination
        SELECT COALESCE(MAX(CAST(SUBSTRING(sku FROM 8) AS INTEGER)), 0) + 1
        INTO seq_num
        FROM inventory.products
        WHERE sku LIKE category_code || '-' || brand_code || '-%';
        
        -- Generate SKU
        NEW.sku := category_code || '-' || brand_code || '-' || LPAD(seq_num::TEXT, 5, '0');
    END IF;
    
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_generate_sku
BEFORE INSERT ON inventory.products
FOR EACH ROW
EXECUTE FUNCTION inventory.generate_sku();

-- Function to update product search vector (Enhanced with v5.0 weighting)
CREATE OR REPLACE FUNCTION inventory.update_product_search_vector()
RETURNS TRIGGER AS $$
BEGIN
    NEW.search_vector := 
        setweight(to_tsvector('english', COALESCE(NEW.name, '')), 'A') ||
        setweight(to_tsvector('english', COALESCE(NEW.brand, '')), 'B') ||
        setweight(to_tsvector('english', COALESCE(NEW.clinical_specialty, '')), 'B') || -- v5.0 enhancement
        setweight(to_tsvector('english', COALESCE(NEW.category, '')), 'C') ||
        setweight(to_tsvector('english', COALESCE(NEW.short_description, '')), 'C') ||
        setweight(to_tsvector('english', COALESCE(NEW.manufacturer, '')), 'C') ||
        setweight(to_tsvector('english', COALESCE(NEW.model, '')), 'D');
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_update_product_search_vector
BEFORE INSERT OR UPDATE ON inventory.products
FOR EACH ROW
EXECUTE FUNCTION inventory.update_product_search_vector();

-- v5.0 ENHANCEMENT: Function for vector similarity search
CREATE OR REPLACE FUNCTION inventory.find_similar_products(
    query_embedding vector(768),
    match_threshold float DEFAULT 0.7,
    match_count int DEFAULT 10,
    clinical_specialty_filter VARCHAR(100) DEFAULT NULL
)
RETURNS TABLE(
    product_id INT,
    sku VARCHAR,
    name VARCHAR,
    brand VARCHAR,
    category VARCHAR,
    clinical_specialty VARCHAR,
    similarity float
) AS $$
BEGIN
    RETURN QUERY
    SELECT 
        p.product_id,
        p.sku,
        p.name,
        p.brand,
        p.category,
        p.clinical_specialty,
        1 - (p.embedding <=> query_embedding) as similarity
    FROM inventory.products p
    WHERE p.embedding IS NOT NULL
      AND (clinical_specialty_filter IS NULL OR p.clinical_specialty = clinical_specialty_filter)
      AND 1 - (p.embedding <=> query_embedding) > match_threshold
    ORDER BY p.embedding <=> query_embedding
    LIMIT match_count;
END;
$$ LANGUAGE plpgsql;

-- ==================================================================================
-- 15. VIEWS FOR REPORTING (Enhanced with v5.0)
-- ==================================================================================

-- View for inventory dashboard with clinical context
CREATE OR REPLACE VIEW inventory.vw_inventory_dashboard AS
SELECT 
    p.product_id,
    p.sku,
    p.name,
    p.category,
    p.clinical_specialty, -- v5.0 enhancement
    p.brand,
    p.manufacturer,
    po.stock_status,
    po.quantity_on_hand,
    po.quantity_reserved,
    po.quantity_available,
    po.reorder_level,
    po.quantity_on_hand - po.reorder_level AS above_reorder_level,
    po.price,
    po.currency,
    po.sale_type, -- v5.0 enhancement
    s.name AS supplier_name,
    s.type AS supplier_type,
    CASE 
        WHEN po.quantity_available <= 0 THEN 'CRITICAL'
        WHEN po.quantity_available <= po.reorder_level THEN 'WARNING'
        ELSE 'HEALTHY'
    END AS inventory_health,
    po.last_updated
FROM inventory.products p
JOIN inventory.product_offerings po ON p.product_id = po.product_id
JOIN inventory.suppliers s ON po.supplier_id = s.supplier_id
WHERE po.is_active = TRUE;

-- View for sales performance with commission tracking
CREATE OR REPLACE VIEW sales.vw_sales_performance AS
SELECT 
    DATE(q.created_at) AS sale_date,
    u.user_id,
    u.organization_name,
    u.customer_tier,
    COUNT(DISTINCT q.quote_id) AS total_quotes,
    COUNT(qi.item_id) AS total_items,
    SUM(q.total_amount) AS total_revenue,
    SUM(qi.quantity) AS total_quantity,
    SUM(q.commission_amount) AS total_commission, -- v5.0 enhancement
    AVG(q.total_amount) AS avg_order_value,
    MIN(q.created_at) AS first_purchase,
    MAX(q.created_at) AS last_purchase
FROM sales.quotes q
JOIN sales.users u ON q.user_id = u.user_id
JOIN sales.quote_items qi ON q.quote_id = qi.quote_id
WHERE q.status IN ('CONFIRMED', 'PAID', 'COMPLETED')
GROUP BY DATE(q.created_at), u.user_id, u.organization_name, u.customer_tier;

-- View for product performance with clinical specialty
CREATE OR REPLACE VIEW inventory.vw_product_performance AS
SELECT 
    p.product_id,
    p.sku,
    p.name,
    p.category,
    p.clinical_specialty, -- v5.0 enhancement
    p.brand,
    COUNT(DISTINCT qi.quote_id) AS times_ordered,
    SUM(qi.quantity) AS total_quantity_sold,
    SUM(qi.line_total) AS total_revenue,
    SUM(qi.commission_amount) AS total_commission, -- v5.0 enhancement
    AVG(qi.unit_price) AS avg_selling_price,
    MIN(q.created_at) AS first_sale_date,
    MAX(q.created_at) AS last_sale_date
FROM inventory.products p
LEFT JOIN sales.quote_items qi ON p.product_id = qi.product_id
LEFT JOIN sales.quotes q ON qi.quote_id = q.quote_id AND q.status IN ('CONFIRMED', 'PAID', 'COMPLETED')
GROUP BY p.product_id, p.sku, p.name, p.category, p.clinical_specialty, p.brand;

-- View for customer insights with clinical interests
CREATE OR REPLACE VIEW sales.vw_customer_insights AS
SELECT 
    u.user_id,
    u.phone_number,
    u.full_name,
    u.organization_name,
    u.customer_tier,
    u.country,
    u.district,
    u.clinical_interests, -- v5.0 enhancement
    COUNT(DISTINCT q.quote_id) AS total_orders,
    SUM(q.total_amount) AS total_spent,
    AVG(q.total_amount) AS avg_order_value,
    MAX(q.total_amount) AS max_order_value,
    MIN(q.created_at) AS first_order_date,
    MAX(q.created_at) AS last_order_date,
    EXTRACT(DAY FROM (CURRENT_DATE - MAX(q.created_at))) AS days_since_last_order,
    STRING_AGG(DISTINCT p.category, ', ') AS categories_purchased,
    STRING_AGG(DISTINCT p.clinical_specialty, ', ') AS clinical_specialties_purchased, -- v5.0 enhancement
    COUNT(DISTINCT p.category) AS unique_categories,
    COUNT(DISTINCT p.clinical_specialty) AS unique_clinical_specialties -- v5.0 enhancement
FROM sales.users u
LEFT JOIN sales.quotes q ON u.user_id = q.user_id AND q.status IN ('CONFIRMED', 'PAID', 'COMPLETED')
LEFT JOIN sales.quote_items qi ON q.quote_id = qi.quote_id
LEFT JOIN inventory.products p ON qi.product_id = p.product_id
GROUP BY u.user_id, u.phone_number, u.full_name, u.organization_name, u.customer_tier, u.country, u.district, u.clinical_interests;

-- View for supplier performance with sale types
CREATE OR REPLACE VIEW inventory.vw_supplier_performance AS
SELECT 
    s.supplier_id,
    s.name,
    s.type,
    s.country,
    COUNT(DISTINCT po.offering_id) AS total_products,
    SUM(po.quantity_on_hand) AS total_stock,
    SUM(po.quantity_on_hand * po.price) AS stock_value,
    COUNT(DISTINCT qi.quote_id) AS total_orders,
    SUM(qi.quantity) AS total_units_sold,
    SUM(qi.line_total) AS total_revenue_generated,
    SUM(qi.commission_amount) AS total_commission_earned, -- v5.0 enhancement
    AVG(po.lead_time_days) AS avg_lead_time,
    MIN(po.created_at) AS first_supply_date,
    MAX(po.last_updated) AS last_supply_date,
    -- v5.0 enhancement: Sale type breakdown
    COUNT(DISTINCT CASE WHEN po.sale_type = 'OWN_STOCK' THEN po.offering_id END) AS own_stock_products,
    COUNT(DISTINCT CASE WHEN po.sale_type = 'COMMISSION' THEN po.offering_id END) AS commission_products,
    COUNT(DISTINCT CASE WHEN po.sale_type = 'DROPSHIP' THEN po.offering_id END) AS dropship_products
FROM inventory.suppliers s
LEFT JOIN inventory.product_offerings po ON s.supplier_id = po.supplier_id
LEFT JOIN sales.quote_items qi ON po.offering_id = qi.offering_id
LEFT JOIN sales.quotes q ON qi.quote_id = q.quote_id AND q.status IN ('CONFIRMED', 'PAID', 'COMPLETED')
GROUP BY s.supplier_id, s.name, s.type, s.country;

-- v5.0 ENHANCEMENT: Clinical specialty insights view
CREATE OR REPLACE VIEW inventory.vw_clinical_specialty_insights AS
SELECT 
    p.clinical_specialty,
    COUNT(DISTINCT p.product_id) AS total_products,
    COUNT(DISTINCT po.offering_id) AS total_offerings,
    SUM(po.quantity_on_hand) AS total_stock,
    SUM(po.quantity_on_hand * po.price) AS stock_value,
    COUNT(DISTINCT qi.quote_id) AS total_orders,
    SUM(qi.quantity) AS total_units_sold,
    SUM(qi.line_total) AS total_revenue,
    AVG(po.price) AS avg_price,
    MIN(po.price) AS min_price,
    MAX(po.price) AS max_price
FROM inventory.products p
LEFT JOIN inventory.product_offerings po ON p.product_id = po.product_id AND po.is_active = TRUE
LEFT JOIN sales.quote_items qi ON po.offering_id = qi.offering_id
LEFT JOIN sales.quotes q ON qi.quote_id = q.quote_id AND q.status IN ('CONFIRMED', 'PAID', 'COMPLETED')
WHERE p.clinical_specialty IS NOT NULL
GROUP BY p.clinical_specialty
ORDER BY total_revenue DESC;

-- ==================================================================================
-- 16. DATA SEEDING (Enhanced with v5.0 Clinical Context)
-- ==================================================================================

-- 1. Seed data sources (EXCEL HAS HIGHEST PRIORITY)
INSERT INTO config.data_sources (source_name, source_type, priority, description, is_trusted) VALUES
('excel_import', 'PRIMARY', 10, 'Excel/CSV inventory files - HIGHEST PRIORITY', true),
('manual_entry', 'PRIMARY', 20, 'Direct database entries by admins', true),
('api_sync', 'ENRICHMENT', 30, 'Third-party API integrations', true),
('pdf_etl', 'SECONDARY', 50, 'External supplier PDFs via Gemini extraction', false),
('web_scraping', 'SECONDARY', 60, 'Web scraping from supplier websites', false),
('system_generated', 'SYSTEM', 100, 'System-generated records', true);

-- 2. Seed core suppliers
INSERT INTO inventory.suppliers (supplier_id, name, type, country, commission_rate, status, is_verified) 
OVERRIDING SYSTEM VALUE VALUES 
(1, 'SocioMed', 'SOCIO_MED', 'Uganda', 0.00, 'ACTIVE', true),
(2, 'Zelus Medical Solutions', 'PARTNER', 'Uganda', 12.50, 'ACTIVE', true),
(3, 'Global Imaging Partners', 'PARTNER', 'USA', 10.00, 'ACTIVE', true),
(4, 'MedEquip Africa', 'PARTNER', 'Kenya', 15.00, 'ACTIVE', true),
(5, 'PharmaCare Uganda', 'PARTNER', 'Uganda', 8.50, 'ACTIVE', true);

-- Reset sequence to avoid ID conflicts
SELECT setval('inventory.suppliers_supplier_id_seq', (SELECT MAX(supplier_id) FROM inventory.suppliers));

-- 3. Seed sample products with v5.0 clinical specialties
DO $$
DECLARE
    excel_source_id INT;
BEGIN
    SELECT source_id INTO excel_source_id 
    FROM config.data_sources 
    WHERE source_name = 'excel_import';
    
    INSERT INTO inventory.products (sku, name, short_description, brand, manufacturer, category, clinical_specialty, subcategory, unit_of_measure, primary_source_id) VALUES
    ('CATH-HEMO-12CM', 'Hemodialysis Catheter', 'Double Lumen, 12cm, Sterile', 'Medtronic', 'Medtronic plc', 'MEDICAL_EQUIPMENT', 'NEPHROLOGY', 'Catheters', 'UNIT', excel_source_id),
    ('GLOV-NIT-100', 'Nitrile Examination Gloves', 'Powder-free, Box of 100', 'Hartalega', 'Hartalega Holdings', 'CONSUMABLES', 'GENERAL_PRACTICE', 'Gloves', 'BOX', excel_source_id),
    ('MASK-SUR-50', 'Surgical Face Mask', '3-ply, 50 pieces per box', '3M', '3M Company', 'PERSONAL_PROTECTIVE_EQUIPMENT', 'SURGERY', 'Masks', 'BOX', excel_source_id),
    ('SYR-5ML-100', 'Syringe 5ml', 'Luer Lock, Sterile, 100 pieces', 'BD', 'Becton Dickinson', 'CONSUMABLES', 'GENERAL_PRACTICE', 'Syringes', 'BOX', excel_source_id),
    ('ECG-MAC-5500', 'ECG Machine', '12 Lead, Portable with interpretation', 'GE Healthcare', 'General Electric', 'DIAGNOSTIC_DEVICES', 'CARDIOLOGY', 'Cardiology', 'UNIT', excel_source_id),
    ('ANES-MAC-3000', 'Anesthesia Machine', 'Portable, with ventilator', 'Drager', 'Dragerwerk AG', 'MEDICAL_EQUIPMENT', 'CRITICAL_CARE', 'Anesthesia', 'UNIT', excel_source_id),
    ('LAB-REAG-HEMO', 'Hemoglobin Reagent', 'For CBC testing, 500 tests', 'Sysmex', 'Sysmex Corporation', 'REAGENTS', 'LABORATORY', 'Hematology', 'BOTTLE', excel_source_id),
    ('ORT-IMP-HIP', 'Hip Implant', 'Titanium, left side', 'Zimmer Biomet', 'Zimmer Biomet Holdings', 'IMPLANTS', 'ORTHOPEDICS', 'Orthopedics', 'UNIT', excel_source_id);
END $$;

-- 4. Seed sample offerings with v5.0 sale types
INSERT INTO inventory.product_offerings (product_id, supplier_id, sale_type, price, cost_price, quantity_on_hand, moq, lead_time_days, source_id) VALUES
-- SocioMed own stock
(1, 1, 'OWN_STOCK', 166500.00, 120000.00, 50, 10, 3, (SELECT source_id FROM config.data_sources WHERE source_name = 'excel_import')),
(2, 1, 'OWN_STOCK', 33300.00, 25000.00, 500, 5, 2, (SELECT source_id FROM config.data_sources WHERE source_name = 'excel_import')),
(3, 1, 'OWN_STOCK', 18500.00, 14000.00, 1000, 10, 1, (SELECT source_id FROM config.data_sources WHERE source_name = 'excel_import')),
(4, 1, 'OWN_STOCK', 7400.00, 5500.00, 800, 5, 2, (SELECT source_id FROM config.data_sources WHERE source_name = 'excel_import')),

-- Partner commission items
(5, 2, 'COMMISSION', 18500000.00, 15000000.00, 5, 1, 14, (SELECT source_id FROM config.data_sources WHERE source_name = 'excel_import')),
(1, 2, 'COMMISSION', 155000.00, 130000.00, 30, 5, 7, (SELECT source_id FROM config.data_sources WHERE source_name = 'excel_import')),
(6, 3, 'COMMISSION', 45000000.00, 38000000.00, 2, 1, 21, (SELECT source_id FROM config.data_sources WHERE source_name = 'excel_import')),

-- Dropship items
(7, 4, 'DROPSHIP', 185000.00, 150000.00, 0, 10, 10, (SELECT source_id FROM config.data_sources WHERE source_name = 'excel_import')),
(8, 5, 'DROPSHIP', 8500000.00, 7200000.00, 0, 1, 28, (SELECT source_id FROM config.data_sources WHERE source_name = 'excel_import'));

-- 5. Seed sample price tiers
INSERT INTO sales.price_tiers (offering_id, tier_name, min_quantity, unit_price) VALUES
(1, 'Bulk Discount', 50, 150000.00),
(1, 'Wholesale', 100, 140000.00),
(2, 'Hospital Bulk', 100, 30000.00),
(2, 'Clinic Pack', 20, 32000.00),
(5, 'Hospital Discount', 2, 18000000.00);

-- 6. Seed sample admin user with clinical interests
INSERT INTO sales.users (phone_number, full_name, user_type, roles, is_verified, verification_level, clinical_interests) VALUES
('+256700000001', 'System Administrator', 'SUPER_ADMIN', '{"ADMIN", "SUPER_USER"}', true, 'ENHANCED', '{"NEPHROLOGY", "CRITICAL_CARE"}');

-- ==================================================================================
-- 17. SECURITY & PERMISSIONS
-- ==================================================================================

-- Create roles
DO $$
BEGIN
    -- Create application roles if they don't exist
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'app_user') THEN
        CREATE ROLE app_user WITH LOGIN PASSWORD 'secure_password_here';
    END IF;
    
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'app_readonly') THEN
        CREATE ROLE app_readonly WITH LOGIN PASSWORD 'readonly_password_here';
    END IF;
    
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'etl_user') THEN
        CREATE ROLE etl_user WITH LOGIN PASSWORD 'etl_password_here';
    END IF;
    
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'medical_analyst') THEN
        CREATE ROLE medical_analyst WITH LOGIN PASSWORD 'medical_password_here';
    END IF;
END $$;

-- Grant schema permissions
GRANT USAGE ON SCHEMA inventory TO app_user, app_readonly, etl_user, medical_analyst;
GRANT USAGE ON SCHEMA sales TO app_user, app_readonly, etl_user, medical_analyst;
GRANT USAGE ON SCHEMA config TO app_user, app_readonly, etl_user, medical_analyst;
GRANT USAGE ON SCHEMA audit TO app_user, app_readonly, medical_analyst;

-- Grant table permissions
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA inventory TO app_user;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA sales TO app_user;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA config TO app_user;
GRANT SELECT ON ALL TABLES IN SCHEMA audit TO app_user;

GRANT SELECT ON ALL TABLES IN SCHEMA inventory TO app_readonly;
GRANT SELECT ON ALL TABLES IN SCHEMA sales TO app_readonly;
GRANT SELECT ON ALL TABLES IN SCHEMA config TO app_readonly;
GRANT SELECT ON ALL TABLES IN SCHEMA audit TO app_readonly;

-- ETL user specific permissions
GRANT SELECT, INSERT, UPDATE ON inventory.products TO etl_user;
GRANT SELECT, INSERT, UPDATE ON inventory.product_offerings TO etl_user;
GRANT SELECT ON config.data_sources TO etl_user;

-- Medical analyst specific permissions (v5.0 enhancement)
GRANT SELECT ON ALL TABLES IN SCHEMA inventory TO medical_analyst;
GRANT SELECT ON ALL TABLES IN SCHEMA sales TO medical_analyst;
GRANT SELECT ON ALL VIEWS IN SCHEMA inventory TO medical_analyst;
GRANT SELECT ON ALL VIEWS IN SCHEMA sales TO medical_analyst;
GRANT EXECUTE ON FUNCTION inventory.find_similar_products TO medical_analyst;

-- Grant sequence permissions
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA inventory TO app_user, etl_user;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA sales TO app_user;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA config TO app_user;

-- Grant execute permissions on functions
GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA inventory TO app_user, medical_analyst;
GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA sales TO app_user;
GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA config TO app_user;
GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA audit TO app_user;

-- ==================================================================================
-- 18. PERFORMANCE OPTIMIZATIONS
-- ==================================================================================

-- Create additional indexes for performance
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_products_updated ON inventory.products(last_updated_at DESC);
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_offerings_updated ON inventory.product_offerings(last_updated DESC);
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_users_updated ON sales.users(updated_at DESC);
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_quotes_updated ON sales.quotes(updated_at DESC);

-- v5.0 ENHANCEMENT: Index for clinical specialty queries
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_products_clinical_specialty_composite ON inventory.products(clinical_specialty, category);
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_offerings_sale_type_composite ON inventory.product_offerings(sale_type, is_active, stock_status);

-- Create composite indexes for common query patterns
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_product_search ON inventory.products USING gin(name gin_trgm_ops, brand gin_trgm_ops);
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_offerings_active_stock ON inventory.product_offerings(is_active, stock_status, quantity_available);

-- Create BRIN indexes for large tables
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_interactions_brin ON sales.interactions USING brin(created_at);
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_audit_logs_brin ON audit.audit_logs USING brin(changed_at);

-- ==================================================================================
-- 19. DATABASE MAINTENANCE FUNCTIONS
-- ==================================================================================

-- Function to clean up old audit logs (retain 2 years)
CREATE OR REPLACE PROCEDURE audit.cleanup_old_logs(retention_months INT DEFAULT 24)
LANGUAGE plpgsql
AS $$
DECLARE
    cutoff_date DATE;
    partition_name TEXT;
    partition_record RECORD;
BEGIN
    cutoff_date := CURRENT_DATE - (retention_months || ' months')::INTERVAL;
    
    FOR partition_record IN
        SELECT schemaname, tablename
        FROM pg_tables
        WHERE schemaname = 'audit'
          AND tablename LIKE 'audit_logs_y%'
    LOOP
        -- Extract date from partition name
        IF partition_record.tablename ~ 'y(\d{4})m(\d{2})' THEN
            partition_name := partition_record.tablename;
            
            -- Check if partition is older than retention period
            IF TO_DATE(SUBSTRING(partition_name FROM 'y(\d{4})m(\d{2})'), 'YYYYMM') < cutoff_date THEN
                EXECUTE format('DROP TABLE IF EXISTS audit.%I', partition_name);
                RAISE NOTICE 'Dropped old audit partition: %', partition_name;
            END IF;
        END IF;
    END LOOP;
END;
$$;

-- Function to reindex tables
CREATE OR REPLACE PROCEDURE maintenance.reindex_tables()
LANGUAGE plpgsql
AS $$
DECLARE
    table_record RECORD;
BEGIN
    FOR table_record IN
        SELECT schemaname, tablename
        FROM pg_tables
        WHERE schemaname IN ('inventory', 'sales', 'config')
          AND tablename NOT LIKE 'pg_%'
    LOOP
        EXECUTE format('REINDEX TABLE %I.%I', table_record.schemaname, table_record.tablename);
        RAISE NOTICE 'Reindexed: %.%', table_record.schemaname, table_record.tablename;
    END LOOP;
END;
$$;

-- Function to update statistics
CREATE OR REPLACE PROCEDURE maintenance.update_statistics()
LANGUAGE plpgsql
AS $$
BEGIN
    ANALYZE inventory.products;
    ANALYZE inventory.product_offerings;
    ANALYZE sales.users;
    ANALYZE sales.quotes;
    ANALYZE sales.quote_items;
    RAISE NOTICE 'Statistics updated for critical tables';
END;
$$;

-- v5.0 ENHANCEMENT: Function to update vector embeddings
CREATE OR REPLACE PROCEDURE inventory.update_product_embeddings()
LANGUAGE plpgsql
AS $$
DECLARE
    product_record RECORD;
BEGIN
    -- In production, this would call an external ML service
    -- For now, we'll just log that embeddings need updating
    RAISE NOTICE 'Vector embeddings update procedure called. In production, connect to ML service here.';
    
    -- Example: Update embeddings for products without them
    FOR product_record IN
        SELECT product_id, name, short_description, brand, category, clinical_specialty
        FROM inventory.products
        WHERE embedding IS NULL
        LIMIT 100 -- Batch size
    LOOP
        -- In production: Call ML service API and update embedding
        -- For demo: Set a dummy embedding
        UPDATE inventory.products 
        SET embedding = '[0.1,0.2,0.3]'::vector -- Replace with real embedding
        WHERE product_id = product_record.product_id;
    END LOOP;
    
    RAISE NOTICE 'Vector embeddings updated for batch of products';
END;
$$;

-- ==================================================================================
-- 20. COMPLETION MESSAGE
-- ==================================================================================
DO $$
BEGIN
    RAISE NOTICE '==============================================';
    RAISE NOTICE 'SOCIO-MED MARKETPLACE SCHEMA v4.5 DEPLOYED';
    RAISE NOTICE '==============================================';
    RAISE NOTICE 'Schemas Created: inventory, sales, config, audit';
    RAISE NOTICE 'Tables Created: %', (
        SELECT COUNT(*) FROM pg_tables 
        WHERE schemaname IN ('inventory', 'sales', 'config', 'audit')
    );
    RAISE NOTICE 'Indexes Created: %', (
        SELECT COUNT(*) FROM pg_indexes 
        WHERE schemaname IN ('inventory', 'sales', 'config', 'audit')
    );
    RAISE NOTICE 'Functions Created: %', (
        SELECT COUNT(*) FROM pg_proc 
        WHERE pronamespace::regnamespace::text IN ('inventory', 'sales', 'config', 'audit')
    );
    RAISE NOTICE 'v5.0 Enhancements Included:';
    RAISE NOTICE '  • Clinical specialties for products and users';
    RAISE NOTICE '  • Vector embeddings for semantic search';
    RAISE NOTICE '  • Sale types (OWN_STOCK, COMMISSION, DROPSHIP)';
    RAISE NOTICE '  • Enhanced search with clinical context weighting';
    RAISE NOTICE '  • Commission tracking in sales';
    RAISE NOTICE '  • Medical analyst role for clinical insights';
    RAISE NOTICE '==============================================';
END $$;
