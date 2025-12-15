-- ==================================================================================
-- SOCIO-MED MARKETPLACE ERP SCHEMA v5.0
-- "Clean Slate" Architecture for Production
-- Features: Medical-Specific, Multi-Source Conflict Resolution, Full-Text Search
-- ==================================================================================

-- 0. INITIAL SETUP
-- ==================================================================================
SET statement_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SET check_function_bodies = false;
SET client_min_messages = warning;

-- Enable Required Extensions
CREATE EXTENSION IF NOT EXISTS pg_trgm;  -- For fuzzy text search (e.g., "cathter" -> "catheter")
CREATE EXTENSION IF NOT EXISTS "uuid-ossp"; -- For unique IDs
CREATE EXTENSION IF NOT EXISTS vector;

-- Create Organizational Schemas (Namespaces)
CREATE SCHEMA IF NOT EXISTS config;    -- System settings & ETL sources
CREATE SCHEMA IF NOT EXISTS inventory; -- Products, Stock, Suppliers
CREATE SCHEMA IF NOT EXISTS sales;     -- Users, Quotes, Transactions
CREATE SCHEMA IF NOT EXISTS audit;     -- Logs

-- 1. CLEAN UP (Reset the database cleanly)
-- ==================================================================================
DROP SCHEMA IF EXISTS audit CASCADE;
DROP SCHEMA IF EXISTS sales CASCADE;
DROP SCHEMA IF EXISTS inventory CASCADE;
DROP SCHEMA IF EXISTS config CASCADE;

-- Re-create schemas after drop
CREATE SCHEMA config;
CREATE SCHEMA inventory;
CREATE SCHEMA sales;
CREATE SCHEMA audit;

-- ==================================================================================
-- 2. CONFIG SCHEMA: DATA GOVERNANCE
-- ==================================================================================

-- Track where data comes from (Excel vs PDF vs API)
CREATE TABLE config.data_sources (
    source_id SERIAL PRIMARY KEY,
    source_name VARCHAR(50) UNIQUE NOT NULL, -- 'excel_import', 'pdf_etl'
    priority INT NOT NULL DEFAULT 100, -- Lower number = Higher Priority (Excel=10, PDF=50)
    description TEXT,
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Seed Data Sources
INSERT INTO config.data_sources (source_name, priority, description) VALUES
('excel_import', 10, 'Verified Inventory Excel - High Trust'),
('manual_entry', 20, 'Admin Manual Entry'),
('api_sync', 30, 'Partner API Integration'),
('pdf_etl', 50, 'AI Extracted PDF - Medium Trust'),
('system', 100, 'System Generated');

-- ==================================================================================
-- 3. INVENTORY SCHEMA: CORE DATA
-- ==================================================================================

-- Suppliers & Partners
CREATE TABLE inventory.suppliers (
    supplier_id SERIAL PRIMARY KEY,
    name VARCHAR(200) NOT NULL UNIQUE,
    code VARCHAR(50) UNIQUE, -- Short code e.g. "MED"
    type VARCHAR(20) CHECK (type IN ('SOCIO_MED', 'PARTNER', 'EXTERNAL', 'MANUFACTURER')) NOT NULL,
    
    -- Commission Settings
    commission_rate DECIMAL(5,2) DEFAULT 0.00, -- e.g., 10.00%
    payment_terms VARCHAR(100),
    
    -- Contact
    country VARCHAR(100),
    contact_email VARCHAR(255),
    contact_phone VARCHAR(50),
    website VARCHAR(255),
    
    -- Integration
    api_config JSONB,
    data_source_id INT REFERENCES config.data_sources(source_id),
    
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Master Product Catalog
CREATE TABLE inventory.products (
    product_id SERIAL PRIMARY KEY,
    sku VARCHAR(100) UNIQUE NOT NULL,
    
    -- Core Identity
    name VARCHAR(500) NOT NULL,
    brand VARCHAR(200),
    manufacturer VARCHAR(200),
    model VARCHAR(200),
    
    -- STRICT MEDICAL CATEGORIZATION
    category VARCHAR(50) NOT NULL CHECK (category IN (
        'REAGENTS',
        'MEDICAL_EQUIPMENT',
        'SURGICAL_INSTRUMENTS',
        'IMPLANTS',
        'MEDICAL_DEVICES',
        'CONSUMABLES',
        'PHARMACEUTICALS', -- Optional extra if needed
        'GENERAL'          -- Fallback
    )),
    
    -- Clinical Context
    clinical_specialty VARCHAR(100) CHECK (clinical_specialty IN (
        'NEPHROLOGY', 'CRITICAL_CARE', 'CARDIOLOGY', 'RADIOLOGY', 
        'SURGERY', 'LABORATORY', 'DENTAL', 'ORTHOPEDICS', 
        'GYNECOLOGY', 'GENERAL_PRACTICE', 'OTHER'
    )),
    
    subcategory VARCHAR(200), -- e.g., 'Catheters', 'Syringes'
    
    -- Descriptions
    short_description VARCHAR(500),
    full_description TEXT,
    upsell_hints TEXT, -- Raw text for relationship parsing
    
    -- Specifications
    unit_of_measure VARCHAR(50) DEFAULT 'UNIT',
    specifications JSONB, -- {"size": "14Fr", "material": "Latex", "sterile": true}
    
    -- Compliance
    requires_prescription BOOLEAN DEFAULT FALSE,
    requires_cold_chain BOOLEAN DEFAULT FALSE, -- Critical for Reagents
    regulatory_status VARCHAR(100),
    embedding vector (768),
    
    -- Source Tracking (For Conflict Resolution)
    primary_source_id INT REFERENCES config.data_sources(source_id),
    last_updated_by_source_id INT REFERENCES config.data_sources(source_id),
    
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    
    -- INSTANT SEARCH (Generated Column)
    -- Automatically maintains a searchable index of Name, Brand, Specialty, and Description
    search_vector tsvector GENERATED ALWAYS AS (
        setweight(to_tsvector('english', COALESCE(name, '')), 'A') ||
        setweight(to_tsvector('english', COALESCE(brand, '')), 'B') ||
        setweight(to_tsvector('english', COALESCE(clinical_specialty, '')), 'B') ||
        setweight(to_tsvector('english', COALESCE(category, '')), 'C') ||
        setweight(to_tsvector('english', COALESCE(short_description, '')), 'C')
    ) STORED
);

-- Search Indexes
CREATE INDEX idx_products_sku ON inventory.products(sku);
CREATE INDEX idx_products_category ON inventory.products(category);
CREATE INDEX idx_products_specialty ON inventory.products(clinical_specialty);
CREATE INDEX idx_products_search_vector ON inventory.products USING GIN(search_vector); -- Fast Full-Text Search

-- Product Offerings (Inventory & Pricing)
CREATE TABLE inventory.product_offerings (
    offering_id SERIAL PRIMARY KEY,
    product_id INT NOT NULL REFERENCES inventory.products(product_id) ON DELETE CASCADE,
    supplier_id INT NOT NULL REFERENCES inventory.suppliers(supplier_id),
    
    -- EXPLICIT COMMISSION LOGIC
    sale_type VARCHAR(20) DEFAULT 'OWN_STOCK' CHECK (sale_type IN (
        'OWN_STOCK',   -- Inventory owned by SocioMed
        'COMMISSION',  -- Consignment/Partner Stock
        'DROPSHIP'     -- External Stock
    )),
    
    supplier_sku VARCHAR(100),
    
    -- Pricing
    price DECIMAL(14,2) NOT NULL,
    currency VARCHAR(3) DEFAULT 'UGX',
    cost_price DECIMAL(14,2), -- For margin calc
    
    -- Inventory Levels
    quantity_on_hand INT DEFAULT 0,
    quantity_reserved INT DEFAULT 0, -- Held in active quotes
    quantity_available INT GENERATED ALWAYS AS (quantity_on_hand - quantity_reserved) STORED,
    
    stock_status VARCHAR(50) DEFAULT 'IN_STOCK',
    lead_time_days INT DEFAULT 0,
    min_order_quantity INT DEFAULT 1,
    
    -- Logistics
