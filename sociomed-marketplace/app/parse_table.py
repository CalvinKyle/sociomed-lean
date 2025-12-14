import os
import csv
from bs4 import BeautifulSoup

# --- CONFIGURATION ---
INPUT_FILE = "data/inputs/outlets.html"
OUTPUT_FILE = "data/outputs/extracted_premises.csv"

# Selectors based on the table headers you provided
SELECTORS = {
    "row_container": "tr", 
    "premise_name": ".column-1",
    "premise_no": ".column-2",
    "premise_type": ".column-3",
    "tpin": ".column-4",
    "address": ".column-5",
    "street": ".column-6",
    "psu": ".column-7",
    "category": ".column-8",
    "district": ".column-9",
    "region": ".column-10"
}

def clean_text(tag):
    """Helper to extract and clean text from a tag"""
    if tag:
        return tag.get_text(strip=True)
    return ""

def parse_html():
    print(f"Loading {INPUT_FILE}...")
    
    try:
        with open(INPUT_FILE, "r", encoding="utf-8") as f:
            soup = BeautifulSoup(f, "html.parser")
    except FileNotFoundError:
        print(f"Error: Could not find {INPUT_FILE}.")
        return

    extracted_rows = []
    
    # Find all table rows
    rows = soup.select(SELECTORS["row_container"])
    print(f"Found {len(rows)} rows. Extracting data...")

    for row in rows:
        # We skip the header row by checking if it contains 'th' elements
        if row.find('th'):
            continue

        # Extract data using the specific column classes
        premise_name = clean_text(row.select_one(SELECTORS["premise_name"]))
        
        # If the row has no name, it might be empty/invalid, skip it
        if not premise_name:
            continue

        premise_no = clean_text(row.select_one(SELECTORS["premise_no"]))
        premise_type = clean_text(row.select_one(SELECTORS["premise_type"]))
        tpin = clean_text(row.select_one(SELECTORS["tpin"]))
        address = clean_text(row.select_one(SELECTORS["address"]))
        street = clean_text(row.select_one(SELECTORS["street"]))
        psu = clean_text(row.select_one(SELECTORS["psu"]))
        category = clean_text(row.select_one(SELECTORS["category"]))
        district = clean_text(row.select_one(SELECTORS["district"]))
        region = clean_text(row.select_one(SELECTORS["region"]))

        extracted_rows.append([
            premise_name, premise_no, premise_type, tpin, 
            address, street, psu, category, district, region
        ])

    # Save to CSV
    os.makedirs(os.path.dirname(OUTPUT_FILE), exist_ok=True)
    with open(OUTPUT_FILE, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        # Write the Header Row
        writer.writerow([
            "Premise Name", "Premise No", "Type", "TPIN", 
            "Physical Address", "Street", "PSU No", "Category", 
            "District", "Region"
        ])
        writer.writerows(extracted_rows)

    print(f"Success! Saved {len(extracted_rows)} records to {OUTPUT_FILE}")

if __name__ == "__main__":
    parse_html()
