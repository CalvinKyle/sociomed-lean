"""
sync_sheets_to_db.py  –  SocioMed Lean
Upsert-safe sync from Google Sheets → PostgreSQL.

Changes vs original:
  - DELETE-ALL replaced with upsert (merge/update).  DB is never empty mid-sync.
  - Redis cache cleared AFTER a successful sync.
  - Alembic run is guarded; failure aborts sync early.
  - Phone numbers normalised before insert.
  - Stale-alias cleanup: aliases whose product_id no longer exists are removed.
"""

import sys
import subprocess
import logging

sys.path.insert(0, ".")

from app.core.sheet_sync import prepare_sheet_data, split_multi_value_cell, summarize_vendor_phone_issues
from app.integrations.sheets import load_data as load_from_sheets
from app.models.db import (
    SessionLocal,
    Product,
    Vendor,
    Inventory,
    Pricing,
    Alias,
    init_db,
)

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")


# ─── helpers ──────────────────────────────────────────────────────────────────

def _coerce_int(value, default=0):
    if value in (None, ""):
        return default
    if isinstance(value, (int, float)):
        return int(value)
    return int(str(value).replace(",", "").strip())


def _upsert(db, model_cls, pk_field: str, rows: list[dict], field_map: dict) -> tuple[int, int]:
    """
    Insert or update rows.  Returns (inserted, updated).
    pk_field: the primary-key column name (string).
    field_map: {sheet_key → model_attr} mapping.
    """
    inserted = updated = 0
    for row in rows:
        pk_value = str(row.get(pk_field, "")).strip()
        if not pk_value:
            continue

        obj = db.get(model_cls, pk_value)
        if obj is None:
            obj = model_cls(**{pk_field: pk_value})
            db.add(obj)
            inserted += 1
        else:
            updated += 1

        for sheet_key, model_attr in field_map.items():
            raw = row.get(sheet_key)
            setattr(obj, model_attr, str(raw).strip() if raw not in (None, "") else None)

    return inserted, updated


# ─── main ─────────────────────────────────────────────────────────────────────

def sync_sheets_to_db():
    logger.info("Starting sync from Google Sheets → PostgreSQL …")

    # 1. Run migrations first. Abort if they fail.
    result = subprocess.run(["alembic", "upgrade", "head"], capture_output=True, text=True)
    if result.returncode != 0:
        logger.error("Alembic migration failed:\n%s", result.stderr)
        sys.exit(1)
    logger.info("Migrations OK")

    # 2. Ensure tables exist (idempotent).
    init_db()

    # 3. Pull from Sheets.
    try:
        raw = load_from_sheets()
    except Exception as exc:
        logger.error("Failed to load from Google Sheets: %s", exc)
        sys.exit(1)

    data = prepare_sheet_data(raw)

    logger.info(
        "Loaded from Sheets: %d products, %d vendors, %d inventory, %d pricing, %d aliases",
        len(data["products"]),
        len(data["vendors"]),
        len(data["inventory"]),
        len(data["pricing"]),
        len(data["aliases"]),
    )

    phone_quality = summarize_vendor_phone_issues(data["vendors"])
    logger.info(
        "Vendor phones — valid: %d, missing: %d, invalid format: %d",
        phone_quality["valid"],
        phone_quality["missing"],
        phone_quality["invalid"],
    )
    if phone_quality["valid"] < 3:
        logger.warning(
            "LAUNCH BLOCKER: fewer than 3 vendors have valid +countrycode phones. "
            "WhatsApp RFQ routing will silently fail."
        )

    # 4. Upsert everything in one transaction.
    db = SessionLocal()
    try:
        # ── products ──
        ins, upd = _upsert(
            db, Product, "product_id",
            data["products"],
            {
                "name": "name",
                "category": "category",
                "clinical_speciality": "clinical_speciality",
                "related_ids": "related_ids",
            },
        )
        logger.info("Products: %d inserted, %d updated", ins, upd)

        # ── vendors ──
        ins, upd = _upsert(
            db, Vendor, "vendor_id",
            data["vendors"],
            {"name": "name", "phone": "phone", "email": "email", "region": "region"},
        )
        logger.info("Vendors: %d inserted, %d updated", ins, upd)

        # ── inventory ──
        for row in data["inventory"]:
            inv_id = str(row.get("inventory_id", "")).strip()
            if not inv_id:
                continue
            obj = db.get(Inventory, inv_id)
            if obj is None:
                obj = Inventory(inventory_id=inv_id)
                db.add(obj)
            obj.product_id = str(row.get("product_id", "")).strip() or None
            obj.vendor_id = str(row.get("vendor_id", "")).strip() or None
            obj.brand = str(row.get("brand", "")).strip() or None
            obj.uom = str(row.get("uom", "")).strip() or None
            obj.stock_qty = _coerce_int(row.get("stock_qty", 0))
            obj.lead_time_days = _coerce_int(row.get("lead_time_days", 0))
        logger.info("Inventory: upserted %d rows", len(data["inventory"]))

        # ── pricing ──
        for row in data["pricing"]:
            pr_id = str(row.get("pricing_id", "")).strip()
            if not pr_id:
                continue
            obj = db.get(Pricing, pr_id)
            if obj is None:
                obj = Pricing(pricing_id=pr_id)
                db.add(obj)
            obj.inventory_id = str(row.get("inventory_id", "")).strip() or None
            obj.min_qty = _coerce_int(row.get("min_qty", 0))
            obj.max_qty = _coerce_int(row.get("max_qty")) if row.get("max_qty") else None
            obj.unit_price = _coerce_int(row.get("unit_price", 0))
        logger.info("Pricing: upserted %d rows", len(data["pricing"]))

        # ── aliases: delete-and-replace is safe because aliases have no FK dependants ──
        valid_product_ids = {str(p.get("product_id", "")).strip() for p in data["products"]}
        db.query(Alias).delete()
        alias_rows = [
            Alias(
                alias=alias,
                product_id=str(a.get("product_id", "")).strip(),
            )
            for a in data["aliases"]
            for alias in split_multi_value_cell(a.get("alias", ""))
            if str(a.get("alias", "")).strip()
            and str(a.get("product_id", "")).strip() in valid_product_ids
        ]
        db.bulk_save_objects(alias_rows)
        logger.info("Aliases: replaced with %d rows (%d stale removed)",
                    len(alias_rows), len(data["aliases"]) - len(alias_rows))

        db.commit()
        logger.info("✅ DB sync successful")

    except Exception as exc:
        db.rollback()
        logger.error("Sync failed — rolled back: %s", exc)
        raise
    finally:
        db.close()

    # 5. Clear Redis cache AFTER a successful sync.
    try:
        from app.core.cache import clear_cache
        cleared = clear_cache()
        if cleared:
            logger.info("Redis cache cleared — next request will serve fresh data")
    except Exception as exc:
        logger.warning("Could not clear Redis cache (non-fatal): %s", exc)

    logger.info("Sync complete.")


if __name__ == "__main__":
    sync_sheets_to_db()
