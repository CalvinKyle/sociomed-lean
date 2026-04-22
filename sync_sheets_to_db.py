import sys
sys.path.insert(0, ".")   # Makes sure Python can find the 'app' folder

from app.core.sheet_sync import prepare_sheet_data, summarize_vendor_phone_issues
from app.integrations.sheets import load_data as load_from_sheets
from app.models.db import (
    SessionLocal,
    Product,
    Vendor,
    Inventory,
    Pricing,
    Alias,
    init_db
)

# Ensure schema is up-to-date before syncing data
import subprocess
subprocess.run(["alembic", "upgrade", "head"], check=True)


def _coerce_int(value, default=0):
    if value in (None, ""):
        return default
    if isinstance(value, (int, float)):
        return int(value)
    return int(str(value).replace(",", "").strip())

def sync_sheets_to_db():
    print("🔄 Starting FULL sync from Google Sheets → PostgreSQL...")

    # 1. Make sure database tables exist
    init_db()
    
    # 2. Pull the latest data from your Google Sheets
    data = prepare_sheet_data(load_from_sheets())
    print(f"📊 Loaded from Sheets: {len(data['products'])} products, "
          f"{len(data['vendors'])} vendors, {len(data['inventory'])} inventory items")
    phone_quality = summarize_vendor_phone_issues(data["vendors"])
    print(
        "📞 Vendor contact quality: "
        f"{phone_quality['valid']} valid, {phone_quality['missing']} missing, {phone_quality['invalid']} not in +countrycode format"
    )
    if phone_quality["valid"] < 3:
        print("⚠️ Launch blocker: fewer than 3 vendors have valid +countrycode phone numbers for WhatsApp routing.")

    # 3. Connect to PostgreSQL
    db = SessionLocal()
    try:
        # Clear old data (safe for MVP — we replace everything each sync)
        print("🧹 Clearing old data...")
        db.query(Product).delete()
        db.query(Vendor).delete()
        db.query(Inventory).delete()
        db.query(Pricing).delete()
        db.query(Alias).delete()
        db.commit()

        # ── PRODUCTS ──
        print("📦 Inserting Products...")
        for p in data["products"]:
            db.add(Product(
                product_id=str(p.get("product_id", "")),
                name=str(p.get("name", "")),
                category=str(p.get("category", ""))
            ))

        # ── VENDORS ──
        print("👥 Inserting Vendors...")
        for v in data["vendors"]:
            db.add(Vendor(
                vendor_id=str(v.get("vendor_id", "")),
                name=str(v.get("name", "")),
                phone=str(v.get("phone", "")),
                email=str(v.get("email", "")),
                region=str(v.get("region", "")),
            ))

        # ── INVENTORY ──
        print("📦 Inserting Inventory...")
        for i in data["inventory"]:
            db.add(Inventory(
                inventory_id=str(i.get("inventory_id", "")),
                product_id=str(i.get("product_id", "")),
                vendor_id=str(i.get("vendor_id", "")),
                brand=str(i.get("brand", "")),
                uom=str(i.get("uom", "")),
                stock_qty=_coerce_int(i.get("stock_qty", 0)),
                lead_time_days=_coerce_int(i.get("lead_time_days", 0)),
            ))

        # ── PRICING ──
        print("💰 Inserting Pricing...")
        for pr in data["pricing"]:
            db.add(Pricing(
                pricing_id=str(pr.get("pricing_id", "")),
                inventory_id=str(pr.get("inventory_id", "")),
                min_qty=_coerce_int(pr.get("min_qty", 0)),
                max_qty=_coerce_int(pr.get("max_qty", 0), default=0) if pr.get("max_qty") else None,
                unit_price=_coerce_int(pr.get("unit_price", 0)),
            ))

        # ── ALIASES ──
        print("🔍 Inserting Aliases...")
        for a in data["aliases"]:
            db.add(Alias(
                alias=str(a.get("alias", "")),
                product_id=str(a.get("product_id", ""))
            ))

        # 4. Save everything
        db.commit()
        print("✅ SYNC SUCCESSFUL! PostgreSQL is now 100% up to date with your Sheets.")

    except Exception as e:
        db.rollback()
        print(f"❌ Sync failed: {e}")
        raise
    finally:
        db.close()

if __name__ == "__main__":
    sync_sheets_to_db()
