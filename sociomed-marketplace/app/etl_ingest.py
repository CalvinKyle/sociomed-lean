#!/usr/bin/env python3
import os
import glob
import json
import re
import time
import google.generativeai as genai
import logging
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any
import traceback

import google.generativeai as genai
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.exc import SQLAlchemyError
from pypdf import PdfReader

# -------------------------- CONFIGURATION --------------------------
DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise ValueError("DATABASE_URL environment variable is NOT set.")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
MAX_PDF_SIZE_DIRECT_UPLOAD = 10 * 1024 * 1024  # 10MB (Gemini's limit for file upload)
MAX_TEXT_LENGTH_DIRECT_PROCESSING = 15000  # Characters
CHUNK_SIZE = 10000  # Characters for text chunking
API_RETRY_ATTEMPTS = 3
API_RETRY_DELAY = 2  # seconds

# Paths
RAW_PDF_DIR = "/data/raw_pdfs"
PROCESSED_PDF_DIR = "/data/processed"
FAILED_PDF_DIR = "/data/failed"
LOG_FILE = "/logs/etl_ingest.log"

# Create directories
for directory in [RAW_PDF_DIR, PROCESSED_PDF_DIR, FAILED_PDF_DIR]:
    Path(directory).mkdir(parents=True, exist_ok=True)

# -------------------------- LOGGING --------------------------
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(LOG_FILE),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("ETL_Ingest")

# -------------------------- INITIALIZATION --------------------------
# Validate API Key
if not GEMINI_API_KEY:
    logger.error("GEMINI_API_KEY environment variable is required")
    raise ValueError("GEMINI_API_KEY environment variable is required")

genai.configure(api_key=GEMINI_API_KEY)

# Database
try:
    engine = create_engine(DATABASE_URL, pool_pre_ping=True, pool_recycle=3600)
    SessionLocal = sessionmaker(bind=engine)
    logger.info("Database connection established")
except Exception as e:
    logger.error(f"Failed to connect to database: {e}")
    raise

# -------------------------- PROMPTS --------------------------
EXTRACTION_PROMPT_DIRECT = """
You are an expert medical equipment data extractor analyzing a supplier pricelist PDF.

Extract structured data and return ONLY valid JSON matching this exact schema:

{
  "supplier_name": "string (required)",
  "supplier_code": "string (optional, infer from filename or content)",
  "country": "string (optional)",
  "contact_email": "string (optional)",
  "currency": "string (e.g., 'USD', 'UGX', 'EUR')",
  "items": [
    {
      "sku": "string (required, use 'UNKNOWN-{increment}' if missing)",
      "name": "string (required, full product name)",
      "description": "string (optional, specifications/details)",
      "brand": "string (optional, manufacturer)",
      "category": "string (required, choose: Surgical Instruments / Consumables / Diagnostics / Radiology / Laboratory / Cardiology / Orthopedics / General Medical)",
      "price": 12.50,
      "currency": "string (optional, defaults to parent currency)",
      "moq": 100,
      "unit": "piece | box | pack | set | case | kit",
      "uom": "string (optional, unit of measure: 'pcs', 'boxes', 'pairs', etc.)"
    }
  ]
}

STRICT RULES:
1. Extract ALL products you find, even if some fields are incomplete
2. If price is missing or unreadable → set price to 0 and add note in description
3. Convert price to UGX 
4. Infer supplier name from filename if not clear in document
5. STRICTLY categorize items into ONLY these categories: medical equipment, devices, consumables, surgical instruments, reagents. If unsure, use 'general'. Do NOT invent new categories.
6. For medical equipment: include size, dimensions, material when available
7. Return ONLY JSON, no markdown, no explanations
"""

EXTRACTION_PROMPT_CHUNKED = """
You are analyzing a CHUNK of a medical equipment pricelist PDF.

Extract product information from this text chunk. Return ONLY a valid JSON list of objects.

Schema for EACH item:
{
  "sku": "string (required, use 'UNKNOWN-{line-number}' if missing)",
  "name": "string (required)",
  "description": "string (optional, specifications)",
  "brand": "string (optional, manufacturer)",
  "category": "string (required)",
  "price": 12.50,
  "currency": "string (optional)",
  "moq": 100,
  "unit": "piece | box | pack | set"
}

RULES for this chunk:
1. Extract all products found in this text section
2. If price missing → set to 0
3. Include supplier context if mentioned: {supplier_context}
4. Focus on medical equipment terms: catheter, stent, glove, suture, scanner, etc.
5. Return empty list [] if no products found
"""

# -------------------------- HELPER FUNCTIONS --------------------------
def clean_json_string(json_str: str) -> str:
    """Advanced cleaning of Gemini response text"""
    # Remove markdown code blocks
    json_str = re.sub(r'```json\s*', '', json_str)
    json_str = re.sub(r'```', '', json_str)
    
    # Remove JavaScript-style comments
    json_str = re.sub(r'//.*?\n', '', json_str)
    json_str = re.sub(r'/\*.*?\*/', '', json_str, flags=re.DOTALL)
    
    # Fix trailing commas in JSON
    json_str = re.sub(r',(\s*[}\]])', r'\1', json_str)
    
    # Remove non-JSON text before and after
    lines = json_str.split('\n')
    json_lines = []
    in_json = False
    
    for line in lines:
        stripped = line.strip()
        if stripped.startswith('{') or stripped.startswith('['):
            in_json = True
        if in_json:
            json_lines.append(line)
        if stripped.endswith('}') or stripped.endswith(']'):
            in_json = False
    
    return '\n'.join(json_lines).strip()

def extract_text_from_pdf(pdf_path: str) -> Optional[str]:
    """Extract text using PyPDF as fallback"""
    try:
        reader = PdfReader(pdf_path)
        text_content = ""
        
        for page_num, page in enumerate(reader.pages):
            extracted = page.extract_text()
            if extracted:
                text_content += f"--- Page {page_num + 1} ---\n{extracted}\n\n"
        
        if not text_content.strip():
            logger.warning(f"No text extracted from {pdf_path}")
            return None
            
        return text_content
    except Exception as e:
        logger.error(f"Failed to extract text from PDF {pdf_path}: {e}")
        return None

def infer_supplier_from_filename(filename: str) -> Tuple[str, Optional[str]]:
    """Extract supplier name and code from filename"""
    # Common patterns in medical supplier filenames
    filename = Path(filename).stem  # Remove extension
    
    # Patterns: SupplierName_Catalog_2024.pdf, Medtronic-PriceList.pdf, JNJ_Products.pdf
    patterns = [
        (r'^([A-Z][A-Za-z\s&]+)_', 'supplier'),  # GE_Healthcare_Catalog
        (r'^([A-Za-z]+)-', 'supplier'),  # Boston-Scientific
        (r'([A-Z]{3,5})_', 'code'),  # BSC_Catalog, JNJ_Price
    ]
    
    supplier_name = None
    supplier_code = None
    
    for pattern, pattern_type in patterns:
        match = re.search(pattern, filename)
        if match:
            if pattern_type == 'supplier':
                supplier_name = match.group(1).replace('_', ' ').title()
            elif pattern_type == 'code':
                supplier_code = match.group(1)
    
    # Fallback: Use filename as supplier name
    if not supplier_name:
        # Clean the filename
        supplier_name = re.sub(r'[_\-]', ' ', filename)
        supplier_name = re.sub(r'\s+(Catalog|Price|List|Products|202[0-9])', '', supplier_name, flags=re.IGNORECASE)
        supplier_name = supplier_name.strip().title()
    
    return supplier_name, supplier_code

def convert_currency(amount: float, from_currency: str, to_currency: str = "UGX") -> Optional[float]:
    """Simple currency conversion (in production, use real API)"""
    # Hardcoded rates for demo - in production use API like exchangerate-api.com
    conversion_rates = {
        "UGX": 0.00027,  # UGX to USD
        "KES": 0.0078,   # KES to USD
        "TZS": 0.00043,  # TZS to USD
        "EUR": 1.08,     # EUR to USD
        "GBP": 1.27,     # GBP to USD
    }
    
    if from_currency.upper() == to_currency.upper():
        return amount
    
    if from_currency.upper() in conversion_rates:
        return amount * conversion_rates[from_currency.upper()]
    
    logger.warning(f"Unknown currency: {from_currency}, assuming {to_currency}")
    return amount  # Assume same currency if unknown

def normalize_product_data(item: Dict, supplier_context: Dict) -> Dict:
    """Clean and normalize extracted product data"""
    normalized = item.copy()
    
    # Ensure required fields
    if not normalized.get('sku'):
        normalized['sku'] = f"UNKNOWN-{int(time.time() * 1000) % 10000}"
    
    if not normalized.get('name'):
        normalized['name'] = f"Unnamed Product {normalized['sku']}"
    
    # Clean price
    price = normalized.get('price')
    if isinstance(price, str):
        # Remove currency symbols, commas, etc.
        price = re.sub(r'[^\d.]', '', price)
        try:
            normalized['price'] = float(price)
        except:
            normalized['price'] = 0.0
            logger.warning(f"Could not parse price: {item.get('price')}")
    elif not isinstance(price, (int, float)):
        normalized['price'] = 0.0
    
    # Set currency
    if not normalized.get('currency') and supplier_context.get('currency'):
        normalized['currency'] = supplier_context['currency']
    elif not normalized.get('currency'):
        normalized['currency'] = 'USD'
    
    # Convert to USD if needed
    if normalized['currency'] != 'USD' and normalized['price'] > 0:
        usd_price = convert_currency(normalized['price'], normalized['currency'])
        if usd_price:
            normalized['price_usd'] = usd_price
            normalized['original_price'] = normalized['price']
            normalized['original_currency'] = normalized['currency']
            normalized['price'] = usd_price
            normalized['currency'] = 'USD'
    
    # Set category
    if not normalized.get('category'):
        # Infer from name
        name_lower = normalized['name'].lower()
        if any(term in name_lower for term in ['glove', 'gown', 'mask', 'syringe']):
            normalized['category'] = 'Consumables'
        elif any(term in name_lower for term in ['catheter', 'stent', 'implant']):
            normalized['category'] = 'Cardiology'
        elif any(term in name_lower for term in ['x-ray', 'ultrasound', 'mri', 'ct']):
            normalized['category'] = 'Radiology'
        else:
            normalized['category'] = 'General Medical'
    
    # Clean description
    if normalized.get('description'):
        # Limit length
        normalized['description'] = normalized['description'][:500]
    
    return normalized

# -------------------------- EXTRACTION FUNCTIONS --------------------------
def extract_with_gemini_direct(pdf_path: str, retry_count: int = API_RETRY_ATTEMPTS) -> Optional[Dict]:
    """Direct PDF upload to Gemini (for smaller files)"""
    for attempt in range(retry_count):
        try:
            logger.info(f"Direct Gemini extraction (attempt {attempt + 1}) for {Path(pdf_path).name}")
            
            # Get file size
            file_size = os.path.getsize(pdf_path)
            if file_size > MAX_PDF_SIZE_DIRECT_UPLOAD:
                logger.warning(f"File too large for direct upload: {file_size/1024/1024:.1f}MB")
                return None
            
            # Upload and process
            uploaded_file = genai.upload_file(pdf_path)
            model = genai.GenerativeModel("gemini-1.5-flash")
            
            # Add filename context to prompt
            filename = Path(pdf_path).name
            supplier_name, supplier_code = infer_supplier_from_filename(filename)
            enhanced_prompt = EXTRACTION_PROMPT_DIRECT + f"\n\nFilename: {filename}\nInferred supplier: {supplier_name}"
            
            response = model.generate_content([enhanced_prompt, uploaded_file])
            
            # Clean and parse response
            clean_response = clean_json_string(response.text)
            data = json.loads(clean_response)
            
            # Add inferred supplier if missing
            if not data.get('supplier_name') and supplier_name:
                data['supplier_name'] = supplier_name
            if supplier_code and not data.get('supplier_code'):
                data['supplier_code'] = supplier_code
            
            logger.info(f"Successfully extracted {len(data.get('items', []))} items via direct upload")
            return data
            
        except json.JSONDecodeError as e:
            logger.error(f"JSON decode error (attempt {attempt + 1}): {e}")
            logger.debug(f"Raw response: {response.text[:500]}...")
            if attempt < retry_count - 1:
                time.sleep(API_RETRY_DELAY * (2 ** attempt))  # Exponential backoff
            else:
                return None
        except Exception as e:
            logger.error(f"Direct extraction failed (attempt {attempt + 1}): {e}")
            if attempt < retry_count - 1:
                time.sleep(API_RETRY_DELAY * (2 ** attempt))
            else:
                return None
    
    return None

def extract_with_gemini_chunked(text: str, filename: str, retry_count: int = API_RETRY_ATTEMPTS) -> Optional[Dict]:
    """Process text chunks through Gemini"""
    supplier_name, supplier_code = infer_supplier_from_filename(filename)
    
    # Split text into chunks
    chunks = [text[i:i + CHUNK_SIZE] for i in range(0, len(text), CHUNK_SIZE)]
    logger.info(f"Split into {len(chunks)} chunks of {CHUNK_SIZE} chars each")
    
    all_items = []
    model = genai.GenerativeModel("gemini-1.5-flash")
    
    for chunk_idx, chunk in enumerate(chunks):
        for attempt in range(retry_count):
            try:
                logger.info(f"Processing chunk {chunk_idx + 1}/{len(chunks)} (attempt {attempt + 1})")
                
                # Prepare chunk-specific prompt
                supplier_context = {
                    'name': supplier_name,
                    'code': supplier_code,
                    'filename': filename
                }
                
                chunk_prompt = EXTRACTION_PROMPT_CHUNKED.format(
                    supplier_context=json.dumps(supplier_context, indent=2)
                )
                
                response = model.generate_content([chunk_prompt, chunk])
                clean_response = clean_json_string(response.text)
                chunk_data = json.loads(clean_response)
                
                if chunk_data and isinstance(chunk_data, list):
                    # Normalize items and add supplier context
                    for item in chunk_data:
                        item['chunk_source'] = chunk_idx + 1
                        normalized = normalize_product_data(item, supplier_context)
                        all_items.append(normalized)
                    
                    logger.info(f"Extracted {len(chunk_data)} items from chunk {chunk_idx + 1}")
                
                break  # Success, move to next chunk
                
            except json.JSONDecodeError as e:
                logger.error(f"JSON error in chunk {chunk_idx + 1} (attempt {attempt + 1}): {e}")
                if attempt < retry_count - 1:
                    time.sleep(API_RETRY_DELAY * (2 ** attempt))
                else:
                    logger.warning(f"Skipping chunk {chunk_idx + 1} after {retry_count} failures")
            except Exception as e:
                logger.error(f"Chunk processing error {chunk_idx + 1} (attempt {attempt + 1}): {e}")
                if attempt < retry_count - 1:
                    time.sleep(API_RETRY_DELAY * (2 ** attempt))
                else:
                    logger.warning(f"Skipping chunk {chunk_idx + 1} after {retry_count} failures")
        
        # Rate limiting between chunks
        time.sleep(1)
    
    if not all_items:
        logger.warning(f"No items extracted from text for {filename}")
        return None
    
    # Compile final result
    result = {
        "supplier_name": supplier_name,
        "supplier_code": supplier_code,
        "filename": filename,
        "extraction_method": "chunked_text",
        "items": all_items
    }
    
    logger.info(f"Extracted total {len(all_items)} items via chunked processing")
    return result

# -------------------------- DATABASE FUNCTIONS --------------------------
def upsert_supplier(session, supplier_data: Dict) -> int:
    """Upsert supplier with enhanced details"""
    result = session.execute(
        text("""
            INSERT INTO suppliers (name, code, country, contact_email, data_source, metadata)
            VALUES (:name, :code, :country, :email, :source, :metadata::jsonb)
            ON CONFLICT (name) DO UPDATE SET
                code = COALESCE(EXCLUDED.code, suppliers.code),
                country = COALESCE(EXCLUDED.country, suppliers.country),
                contact_email = COALESCE(EXCLUDED.contact_email, suppliers.contact_email),
                data_source = EXCLUDED.data_source,
                metadata = COALESCE(suppliers.metadata, '{}'::jsonb) || EXCLUDED.metadata,
                updated_at = CURRENT_TIMESTAMP
            RETURNING id
        """),
        {
            "name": supplier_data.get("supplier_name", "Unknown Supplier"),
            "code": supplier_data.get("supplier_code"),
            "country": supplier_data.get("country", ""),
            "email": supplier_data.get("contact_email", ""),
            "source": supplier_data.get("filename", "manual"),
            "metadata": json.dumps({
                "extraction_method": supplier_data.get("extraction_method", "unknown"),
                "processed_at": datetime.now().isoformat()
            })
        }
    )
    return result.scalar_one()

def upsert_product(session, item: Dict, supplier_id: int) -> Tuple[int, bool]:
    # We assign a low score because AI can make mistakes
    TRUST_SCORE_PDF = 10 
    
    result = session.execute(
        text("""
            INSERT INTO products (
                sku, name, description, brand, category, 
                data_source, trust_score, specifications
            )
            VALUES (
                :sku, :name, :desc, :brand, :category, 
                'GEMINI_PDF', :score, :specs
            )
            ON CONFLICT (sku) DO UPDATE SET
                -- ONLY UPDATE if the existing data is "weaker" than this PDF
                description = EXCLUDED.description,
                specifications = EXCLUDED.specifications,
                category = EXCLUDED.category
            WHERE products.trust_score <= EXCLUDED.trust_score
            RETURNING id
        """),
        {
            "sku": item.get("sku"),
            "name": item.get("name"),
            "desc": item.get("description"),
            "brand": item.get("brand"),
            "category": item.get("category", "general").lower(), # Force lowercase
            "score": TRUST_SCORE_PDF,
            "specs": json.dumps(item)
        }
    """Upsert product with duplicate detection"""
    # Check for existing similar product
    existing = session.execute(
        text("""
            SELECT product_id, name, sku FROM products 
            WHERE (sku = :sku AND sku IS NOT NULL AND sku != '')
               OR (name ILIKE :name AND category = :category)
            LIMIT 1
        """),
        {
            "sku": item.get("sku", ""),
            "name": f"%{item.get('name')}%",
            "category": item.get("category", "General Medical")
        }
    ).fetchone()
    
    if existing:
        product_id = existing[0]
        is_new = False
        logger.debug(f"Found existing product: {existing[1]} (ID: {product_id})")
    else:
        # Insert new product
        result = session.execute(
            text("""
                INSERT INTO products (sku, name, description, brand, category, unit, uom, specifications)
                VALUES (:sku, :name, :desc, :brand, :category, :unit, :uom, :specs::jsonb)
                RETURNING id
            """),
            {
                "sku": item.get("sku"),
                "name": item.get("name"),
                "desc": item.get("description", ""),
                "brand": item.get("brand", item.get("manufacturer", "Generic")),
                "category": item.get("category", "General Medical"),
                "unit": item.get("unit", "piece"),
                "uom": item.get("uom", ""),
                "specs": json.dumps({
                    "original_data": {k: v for k, v in item.items() if k not in ['sku', 'name', 'description', 'brand', 'category', 'price', 'currency', 'moq', 'unit', 'uom']},
                    "extraction_timestamp": datetime.now().isoformat()
                })
            }
        )
        product_id = result.scalar_one()
        is_new = True
    
    return product_id, is_new

    # Generate embedding from description
    description = product.get('full_description') or product.get('short_description') or product['name']
    if description and gemini_model:
        try:
            result = genai.embed_content(
                model="models/embedding-001",
                content=description,
                task_type="retrieval_document"
            )
            embedding = result['embedding']
            
            # Save to database
            session.execute(
                text("UPDATE products SET embedding = :emb WHERE id = :pid"),
                {"emb": embedding, "pid": product_id}
            )
            session.commit()
            logger.info(f"Created smart embedding for {product['name']}")
        except Exception as e:
            logger.error(f"Embedding error: {e}")

def upsert_offering(session, product_id: int, supplier_id: int, item: Dict):
    """Upsert product offering with price history tracking"""
    session.execute(
        text("""
            INSERT INTO product_offerings (product_id, supplier_id, price, currency, moq, is_active, metadata)
            VALUES (:pid, :sid, :price, :curr, :moq, true, :metadata::jsonb)
            ON CONFLICT (product_id, supplier_id) DO UPDATE SET
                price = EXCLUDED.price,
                currency = EXCLUDED.currency,
                moq = EXCLUDED.moq,
                is_active = true,
                last_updated = CURRENT_TIMESTAMP,
                metadata = COALESCE(product_offerings.metadata, '{}'::jsonb) || jsonb_build_object(
                    'previous_price', product_offerings.price,
                    'previous_currency', product_offerings.currency,
                    'price_changed_at', CURRENT_TIMESTAMP
                )
        """),
        {
            "pid": product_id,
            "sid": supplier_id,
            "price": item.get("price", 0),
            "curr": item.get("currency", "USD"),
            "moq": item.get("moq", 1),
            "metadata": json.dumps({
                "original_price": item.get("original_price"),
                "original_currency": item.get("original_currency"),
                "converted_to_usd": 'price_usd' in item,
                "extraction_source": item.get("chunk_source", "direct"),
                "processed_at": datetime.now().isoformat()
            })
        }
    )

# -------------------------- MAIN ETL PIPELINE --------------------------
def process_pdf_file(pdf_path: str) -> Tuple[bool, str]:
    """Process a single PDF file through the enhanced pipeline"""
    filename = Path(pdf_path).name
    logger.info(f"Processing PDF: {filename}")
    
    session = None
    try:
        # METHOD 1: Try direct Gemini upload (for smaller files)
        file_size = os.path.getsize(pdf_path)
        if file_size <= MAX_PDF_SIZE_DIRECT_UPLOAD:
            data = extract_with_gemini_direct(pdf_path)
        
        # METHOD 2: Fall back to text extraction + chunking
        if not data:
            logger.info(f"Falling back to text extraction for {filename}")
            text_content = extract_text_from_pdf(pdf_path)
            if not text_content:
                return False, "Failed to extract text from PDF"
            
            data = extract_with_gemini_chunked(text_content, filename)
        
        if not data or not data.get("items"):
            logger.warning(f"No data extracted from {filename}")
            return False, "No data extracted"
        
        # DATABASE INSERTION
        session = SessionLocal()
        
        # Upsert supplier
        supplier_id = upsert_supplier(session, data)
        
        # Process items
        items_processed = 0
        items_skipped = 0
        new_products = 0
        
        for item in data["items"]:
            try:
                # Skip items with no price or zero price
                if not item.get("price") or float(item.get("price", 0)) == 0:
                    items_skipped += 1
                    continue
                
                # Upsert product
                product_id, is_new = upsert_product(session, item, supplier_id)
                if is_new:
                    new_products += 1
                
                # Upsert offering
                upsert_offering(session, product_id, supplier_id, item)
                
                items_processed += 1
                
            except Exception as e:
                logger.error(f"Error processing item {item.get('sku', 'unknown')}: {e}")
                items_skipped += 1
                continue
        
        # Commit transaction
        session.commit()
        
        logger.info(f"Successfully processed {filename}:")
        logger.info(f"  - Items processed: {items_processed}")
        logger.info(f"  - New products: {new_products}")
        logger.info(f"  - Items skipped: {items_skipped}")
        
        # Move to processed directory
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        new_filename = f"{Path(pdf_path).stem}_{timestamp}{Path(pdf_path).suffix}"
        new_path = os.path.join(PROCESSED_PDF_DIR, new_filename)
        os.rename(pdf_path, new_path)
        
        # Log processing summary
        summary = {
            "filename": filename,
            "supplier": data.get("supplier_name"),
            "items_extracted": len(data.get("items", [])),
            "items_processed": items_processed,
            "new_products": new_products,
            "items_skipped": items_skipped,
            "processing_time": datetime.now().isoformat(),
            "method": data.get("extraction_method", "unknown")
        }
        
        logger.info(f"Processing summary: {json.dumps(summary, indent=2)}")
        
        return True, f"Processed {items_processed} items, {new_products} new products"
        
    except Exception as e:
        if session:
            session.rollback()
        
        logger.error(f"Failed to process {filename}: {e}")
        logger.error(traceback.format_exc())
        
        # Move to failed directory
        failed_path = os.path.join(FAILED_PDF_DIR, filename)
        os.rename(pdf_path, failed_path)
        
        return False, str(e)
    
    finally:
        if session:
            session.close()

def run_etl_pipeline():
    """Main ETL pipeline runner"""
    logger.info("=" * 60)
    logger.info("Starting Enhanced ETL Pipeline")
    logger.info("=" * 60)
    
    # Check for PDFs
    pdf_files = glob.glob(os.path.join(RAW_PDF_DIR, "*.pdf"))
    if not pdf_files:
        logger.info("No PDF files found in raw directory")
        return
    
    logger.info(f"Found {len(pdf_files)} PDF(s) to process")
    
    # Process each PDF
    results = {
        "total_files": len(pdf_files),
        "successful": 0,
        "failed": 0,
        "details": []
    }
    
    for pdf_path in pdf_files:
        success, message = process_pdf_file(pdf_path)
        
        result_detail = {
            "file": Path(pdf_path).name,
            "success": success,
            "message": message,
            "timestamp": datetime.now().isoformat()
        }
        
        if success:
            results["successful"] += 1
            logger.info(f"✓ {Path(pdf_path).name}: {message}")
        else:
            results["failed"] += 1
            logger.error(f"✗ {Path(pdf_path).name}: {message}")
        
        results["details"].append(result_detail)
        
        # Brief pause between files
        time.sleep(1)
    
    # Final summary
    logger.info("=" * 60)
    logger.info("ETL Pipeline Complete")
    logger.info("=" * 60)
    logger.info(f"Total files: {results['total_files']}")
    logger.info(f"Successful: {results['successful']}")
    logger.info(f"Failed: {results['failed']}")
    logger.info(f"Success rate: {(results['successful']/results['total_files']*100):.1f}%")
    
    # Save results log
    results_log = {
        "run_timestamp": datetime.now().isoformat(),
        "summary": results
    }
    
    results_file = os.path.join(LOG_FILE.replace(".log", f"_{datetime.now():%Y%m%d_%H%M%S}_results.json"))
    with open(results_file, 'w') as f:
        json.dump(results_log, f, indent=2)
    
    logger.info(f"Detailed results saved to: {results_file}")

# -------------------------- ENTRY POINT --------------------------
if __name__ == "__main__":
    try:
        # Initial delay for database readiness (useful in Docker)
        logger.info("Waiting for database to be ready...")
        time.sleep(5)
        
        # Run pipeline
        run_etl_pipeline()
        
    except KeyboardInterrupt:
        logger.info("ETL pipeline interrupted by user")
    except Exception as e:
        logger.error(f"Fatal error in ETL pipeline: {e}")
        logger.error(traceback.format_exc())
        raise
