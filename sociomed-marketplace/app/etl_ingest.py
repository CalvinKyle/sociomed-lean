#!/usr/bin/env python3
import os
import glob
import json
import re
import time
import logging
import csv
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any
import traceback
import hashlib

import google.generativeai as genai
from pypdf import PdfReader
import pandas as pd

# -------------------------- CONFIGURATION --------------------------
# Ensure you set this in your .env file
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

# Settings
MAX_PDF_SIZE_DIRECT_UPLOAD = 10 * 1024 * 1024  # 10MB limit for direct API upload
API_RETRY_ATTEMPTS = 3
API_RETRY_DELAY = 2

# Directory Structure
BASE_DIR = "/app/data"  # Adjust based on your Docker structure
RAW_PDF_DIR = os.path.join(BASE_DIR, "inputs")
PROCESSED_PDF_DIR = os.path.join(BASE_DIR, "processed")
FAILED_PDF_DIR = os.path.join(BASE_DIR, "failed")
OUTPUT_DIR = os.path.join(BASE_DIR, "outputs")
LOG_FILE = "/app/logs/etl_ingest.log"

# Create directories if they don't exist
for directory in [RAW_PDF_DIR, PROCESSED_PDF_DIR, FAILED_PDF_DIR, OUTPUT_DIR, os.path.dirname(LOG_FILE)]:
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
if not GEMINI_API_KEY:
    logger.error("GEMINI_API_KEY environment variable is missing.")
    raise ValueError("GEMINI_API_KEY environment variable is required")

genai.configure(api_key=GEMINI_API_KEY)

# -------------------------- SMART PROMPTS --------------------------
# This prompt is engineered to extract "Variants" (Generic Name + Attributes)
EXTRACTION_PROMPT = """
You are an expert medical equipment data analyst. Your goal is to extract product data from a supplier pricelist PDF and structure it for an Odoo ERP import.

**CRITICAL TASK: VARIANT DETECTION**
You must distinguish between the "Generic Product" (Template) and the specific "Variant" (e.g., Size, Material).
Example: "Foley Catheter 12Fr" and "Foley Catheter 14Fr" are the SAME generic product ("Foley Catheter") with different "Size" attributes.

Return ONLY valid JSON matching this schema:
{
  "supplier_name": "string (inferred from document)",
  "supplier_code": "string (optional short code, e.g., 'STS')",
  "currency": "string (e.g., 'UGX', 'USD')",
  "items": [
    {
      "vendor_sku": "string (The specific code listed in the PDF. If missing, leave null)",
      "generic_name": "string (The clean, parent name WITHOUT specific size/color info. e.g., 'Hemodialysis Catheter')",
      "full_name": "string (The complete name as listed. e.g., 'Hemodialysis Catheter 12Fr Double Lumen')",
      "description": "string (Technical specs, material, etc.)",
      "category": "string (Classify into: Nephrology / Cardiology / Consumables / Instruments / Orthopedics / General)",
      "price": 123000,
      "moq": 1,
      "uom": "string (Unit, Box of 10, Set, etc.)",
      "lead_time_days": 14,
      "attributes": {
        "Size": "string (e.g., '12Fr', '10cm x 10cm')",
        "Color": "string",
        "Material": "string",
        "Type": "string (e.g., 'Double Lumen', 'Curved')"
      }
    }
  ]
}

**RULES:**
1. **Generic Name:** Be aggressive in grouping. "Nitrile Gloves Small" and "Nitrile Gloves Large" -> Generic Name: "Nitrile Gloves".
2. **Attributes:** Extract ANY distinguishing feature (Size, Volume, Gauge, Length) into the `attributes` dictionary.
3. **Price:** Extract numerical value only. If missing, set to 0.
4. **JSON Only:** Do not include markdown formatting or explanations.
"""

# -------------------------- HELPER FUNCTIONS --------------------------
def clean_json_string(json_str: str) -> str:
    """Removes Markdown formatting and cleanup JSON string."""
    json_str = re.sub(r'```json\s*', '', json_str)
    json_str = re.sub(r'```', '', json_str)
    # Remove JS-style comments
    json_str = re.sub(r'//.*?\n', '', json_str)
    return json_str.strip()

def generate_smart_sku(supplier_code: str, generic_name: str, attributes: Dict) -> str:
    """
    Generates a consistent SKU if the vendor didn't provide one.
    Format: SUP-GENERIC-ATTR1-ATTR2
    """
    # Create base from Generic Name (e.g., "HEMO-CATH")
    clean_name = re.sub(r'[^a-zA-Z0-9]', '', generic_name.upper())[:8]
    base = f"{supplier_code}-{clean_name}"
    
    # Append Attributes (e.g., "-12FR-DOUBLE")
    attr_parts = []
    for k, v in attributes.items():
        val_clean = re.sub(r'[^a-zA-Z0-9]', '', str(v).upper())[:6]
        attr_parts.append(val_clean)
    
    if attr_parts:
        return f"{base}-" + "-".join(attr_parts)
    
    # Fallback unique ID if no attributes
    unique_suffix = hashlib.md5(f"{generic_name}{time.time()}".encode()).hexdigest()[:4].upper()
    return f"{base}-{unique_suffix}"

def infer_supplier_code(supplier_name: str) -> str:
    """Generates a 3-letter code from supplier name."""
    if not supplier_name:
        return "SUP"
    # Take first 3 letters of first word, or Initials
    parts = supplier_name.split()
    if len(parts) > 1:
        return "".join([p[0] for p in parts[:3]]).upper()
    return supplier_name[:3].upper()

# -------------------------- EXTRACTION LOGIC --------------------------
def extract_data_from_pdf(pdf_path: str) -> Optional[Dict]:
    """
    Orchestrates the extraction process.
    Uses Direct Upload for small PDFs, Text Extraction for large ones.
    """
    filename = Path(pdf_path).name
    try:
        model = genai.GenerativeModel("gemini-1.5-flash")
        file_size = os.path.getsize(pdf_path)
        
        response_text = ""

        # STRATEGY 1: Direct File Upload (Best for layouts/tables)
        if file_size <= MAX_PDF_SIZE_DIRECT_UPLOAD:
            logger.info(f"Uploading {filename} directly to Gemini...")
            uploaded_file = genai.upload_file(pdf_path)
            
            # Wait for processing state
            while uploaded_file.state.name == "PROCESSING":
                time.sleep(1)
                uploaded_file = genai.get_file(uploaded_file.name)

            if uploaded_file.state.name == "FAILED":
                raise ValueError("Gemini file processing failed.")

            response = model.generate_content([EXTRACTION_PROMPT, uploaded_file])
            response_text = response.text
            
            # Cleanup remote file
            genai.delete_file(uploaded_file.name)

        # STRATEGY 2: Text Extraction (Fallback for large files)
        else:
            logger.info(f"File {filename} too large ({file_size} bytes). Using text extraction fallback.")
            reader = PdfReader(pdf_path)
            text_content = ""
            # Extract text from first 20 pages to avoid context limit
            for i, page in enumerate(reader.pages[:20]):
                text_content += f"--- Page {i+1} ---\n{page.extract_text()}\n"
            
            prompt_with_data = EXTRACTION_PROMPT + f"\n\nPDF TEXT CONTENT:\n{text_content}"
            response = model.generate_content(prompt_with_data)
            response_text = response.text

        # Parse Response
        cleaned_json = clean_json_string(response_text)
        return json.loads(cleaned_json)

    except Exception as e:
        logger.error(f"Extraction failed for {filename}: {e}")
        logger.error(traceback.format_exc())
        return None

# -------------------------- DATA MAPPING & CSV EXPORT --------------------------
def map_to_csv_structure(extracted_data: Dict) -> Tuple[List[Dict], List[Dict]]:
    """
    Transforms extracted JSON into:
    1. Products List (for Odoo Product Import)
    2. Offerings List (for Odoo Supplier Info Import)
    """
    products_rows = []
    offerings_rows = []
    
    supplier_name = extracted_data.get('supplier_name', 'Unknown Supplier')
    supplier_code = extracted_data.get('supplier_code') or infer_supplier_code(supplier_name)
    currency = extracted_data.get('currency', 'UGX')
    
    for item in extracted_data.get('items', []):
        # 1. Identity Logic
        vendor_sku = item.get('vendor_sku')
        attributes = item.get('attributes', {})
        
        # If Vendor SKU is missing, generate one
        if not vendor_sku or vendor_sku.lower() == 'null':
            internal_sku = generate_smart_sku(supplier_code, item['generic_name'], attributes)
            vendor_ref = internal_sku # Fallback
        else:
            internal_sku = vendor_sku # Ideally, map this to internal if 1:1 match
            vendor_ref = vendor_sku

        # 2. PRODUCT ROW (The Master Record)
        # Odoo mapping: Name = Generic Name (Template), SKU = Internal Reference
        product_row = {
            'name': item['generic_name'],         # Maps to: Name (Template)
            'default_code': internal_sku,         # Maps to: Internal Reference
            'description_sale': item.get('description', ''), # Maps to: Sales Description
            'categ_id': item.get('category', 'All'),
            'type': 'product',                    # 'product' = Storable, 'consu' = Consumable
            'uom_name': item.get('uom', 'Unit'),
            'list_price': item.get('price', 0),   # This is SALES price. Adjust if markup needed.
            'standard_price': item.get('price', 0), # Cost price placeholder
            'tags': supplier_name
        }
        
        # Add dynamic attributes (e.g., Attribute: Size -> 10Fr)
        for attr_key, attr_val in attributes.items():
            if attr_val:
                col_name = f"Attribute: {attr_key}"
                product_row[col_name] = attr_val
            
        products_rows.append(product_row)
        
        # 3. OFFERING ROW (The Supplier Link)
        offering_row = {
            'product_sku': internal_sku,          # Link to Product
            'supplier_name': supplier_name,       # Link to Vendor
            'vendor_product_code': vendor_ref,    # Vendor's Code
            'price': item.get('price', 0),        # Cost Price
            'currency': currency,
            'min_qty': item.get('moq', 1),
            'lead_time_days': item.get('lead_time_days', 1)
        }
        offerings_rows.append(offering_row)

    return products_rows, offerings_rows

def save_to_csv(data_list: List[Dict], output_filename: str):
    """
    Saves data to CSV. Appends if file exists, ensuring all headers are present.
    """
    if not data_list:
        return
    
    file_path = os.path.join(OUTPUT_DIR, output_filename)
    df_new = pd.DataFrame(data_list)
    
    if os.path.exists(file_path):
        # Load existing to merge headers (in case new attributes appeared)
        df_existing = pd.read_csv(file_path)
        df_combined = pd.concat([df_existing, df_new], ignore_index=True)
    else:
        df_combined = df_new
        
    # Write back
    df_combined.to_csv(file_path, index=False)
    logger.info(f"Updated {output_filename} with {len(data_list)} rows.")

# -------------------------- MAIN PIPELINE --------------------------
def run_pipeline():
    logger.info("="*60)
    logger.info("STARTING PDF INGESTION PIPELINE")
    logger.info("="*60)
    
    pdf_files = glob.glob(os.path.join(RAW_PDF_DIR, "*.pdf"))
    
    if not pdf_files:
        logger.info("No PDF files found in inputs directory.")
        return

    logger.info(f"Found {len(pdf_files)} PDF(s) to process.")
    
    for pdf_path in pdf_files:
        filename = Path(pdf_path).name
        logger.info(f"Processing: {filename}")
        
        # 1. Extract
        data = extract_data_from_pdf(pdf_path)
        
        if not data or not data.get('items'):
            logger.warning(f"No valid data extracted from {filename}. Moving to failed.")
            os.rename(pdf_path, os.path.join(FAILED_PDF_DIR, filename))
            continue
            
        # 2. Map
        try:
            prod_rows, offer_rows = map_to_csv_structure(data)
            
            # 3. Save
            if prod_rows:
                save_to_csv(prod_rows, "extracted_products.csv")
            if offer_rows:
                save_to_csv(offer_rows, "extracted_offerings.csv")
            
            # 4. Move to Processed
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            new_name = f"{Path(filename).stem}_{timestamp}.pdf"
            os.rename(pdf_path, os.path.join(PROCESSED_PDF_DIR, new_name))
            logger.info(f"Successfully processed {filename}")
            
        except Exception as e:
            logger.error(f"Error mapping/saving data for {filename}: {e}")
            logger.error(traceback.format_exc())
            os.rename(pdf_path, os.path.join(FAILED_PDF_DIR, filename))

    logger.info("Pipeline Complete. Files ready in /data/outputs/")

if __name__ == "__main__":
    run_pipeline()
