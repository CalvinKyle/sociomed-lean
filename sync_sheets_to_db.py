import sys
sys.path.insert(0, ".")   # Makes sure Python can find the 'app' folder

from app.sheets import load_data as load_from_sheets
from app.db import (
    SessionLocal,
    Product,
    Vendor,
    Inventory,
    Pricing,
    Alias,
    init_db
)

def sync_sheets_to_db():
    print("🔄 Starting FULL sync from Google Sheets → PostgreSQL...")

    # 1. Make sure database tables exist
    init_db()
    
    # 2. Pull the latest data from your Google Sheets
    data = load_from_sheets()
    print(f"📊 Loaded from Sheets: {len(data['products'])} products, "
          f"{len(data['vendors'])} vendors, {len(data['inventory'])} inventory items")

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
                phone=str(v.get("phone", ""))
            ))

        # ── INVENTORY ──
        print("📦 Inserting Inventory...")
        for i in data["inventory"]:
            db.add(Inventory(
                inventory_id=str(i.get("inventory_id", "")),
                product_id=str(i.get("product_id", "")),
                vendor_id=str(i.get("vendor_id", "")),
                brand=str(i.get("brand", "")),
                stock_qty=int(i.get("stock_qty", 0) or 0),
                lead_time_days=int(i.get("lead_time_days", 0) or 0)
            ))

        # ── PRICING ──
        print("💰 Inserting Pricing...")
        for pr in data["pricing"]:
            db.add(Pricing(
                pricing_id=str(pr.get("pricing_id", "")),
                inventory_id=str(pr.get("inventory_id", "")),
                min_qty=int(pr.get("min_qty", 0) or 0),
                max_qty=int(pr.get("max_qty", 0) or 0) if pr.get("max_qty") else None,
                unit_price=int(pr.get("unit_price", 0) or 0)
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
