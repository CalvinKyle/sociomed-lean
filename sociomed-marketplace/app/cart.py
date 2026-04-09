"""
CartManager — SQLite-backed shopping cart.

SQLite lives in a single file (data/sessions.db).
No Redis, no external service required.
Cart entries expire after 7 days via a cleanup job.
"""

import json
import sqlite3
import logging
import threading
import time
from datetime import datetime, timedelta
from typing import List, Optional

logger = logging.getLogger(__name__)

CART_TTL_DAYS = 7
CLEANUP_INTERVAL_HOURS = 6


class CartManager:
    def __init__(self, db_path: str = "data/sessions.db"):
        self.db_path = db_path
        self._init_db()
        self._start_cleanup_thread()

    # ── Public API ─────────────────────────────────────────────────────────

    def add(self, phone: str, product: dict, qty: int = 1):
        """Add or increment a product in the cart."""
        conn = self._conn()
        existing = conn.execute(
            "SELECT id, qty FROM cart_items WHERE phone=? AND product_id=?",
            (phone, product["product_id"])
        ).fetchone()

        if existing:
            conn.execute(
                "UPDATE cart_items SET qty=?, updated_at=? WHERE id=?",
                (existing[1] + qty, _now(), existing[0])
            )
        else:
            conn.execute(
                """INSERT INTO cart_items
                   (phone, product_id, name, price_ugx, unit, qty, added_at, updated_at)
                   VALUES (?,?,?,?,?,?,?,?)""",
                (
                    phone,
                    product["product_id"],
                    product["name"],
                    product["price_ugx"],
                    product.get("unit", "Each"),
                    qty,
                    _now(), _now(),
                )
            )
        conn.commit()
        conn.close()

    def get(self, phone: str) -> List[dict]:
        conn = self._conn()
        rows = conn.execute(
            "SELECT product_id, name, price_ugx, unit, qty FROM cart_items "
            "WHERE phone=? ORDER BY added_at ASC",
            (phone,)
        ).fetchall()
        conn.close()
        return [
            {
                "product_id": r[0], "name": r[1],
                "price_ugx": r[2], "unit": r[3], "qty": r[4]
            }
            for r in rows
        ]

    def remove(self, phone: str, index: int) -> dict:
        items = self.get(phone)
        if index < 0 or index >= len(items):
            raise IndexError("Invalid cart index")
        item = items[index]
        conn = self._conn()
        conn.execute(
            "DELETE FROM cart_items WHERE phone=? AND product_id=?",
            (phone, item["product_id"])
        )
        conn.commit()
        conn.close()
        return item

    def clear(self, phone: str):
        conn = self._conn()
        conn.execute("DELETE FROM cart_items WHERE phone=?", (phone,))
        conn.commit()
        conn.close()

    # ── Internal ───────────────────────────────────────────────────────────

    def _conn(self) -> sqlite3.Connection:
        return sqlite3.connect(self.db_path)

    def _init_db(self):
        conn = self._conn()
        conn.execute("""
            CREATE TABLE IF NOT EXISTS cart_items (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                phone      TEXT NOT NULL,
                product_id TEXT NOT NULL,
                name       TEXT,
                price_ugx  REAL,
                unit       TEXT,
                qty        INTEGER DEFAULT 1,
                added_at   TEXT,
                updated_at TEXT
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS demand_misses (
                id    INTEGER PRIMARY KEY AUTOINCREMENT,
                ts    TEXT,
                phone TEXT,
                query TEXT
            )
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_cart_phone ON cart_items(phone)
        """)
        conn.commit()
        conn.close()

    def _start_cleanup_thread(self):
        def _runner():
            while True:
                time.sleep(CLEANUP_INTERVAL_HOURS * 3600)
                cutoff = (datetime.utcnow() - timedelta(days=CART_TTL_DAYS)).isoformat()
                conn = self._conn()
                conn.execute("DELETE FROM cart_items WHERE updated_at < ?", (cutoff,))
                conn.commit()
                conn.close()
                logger.info("Cart cleanup complete")

        t = threading.Thread(target=_runner, daemon=True)
        t.start()


def _now() -> str:
    return datetime.utcnow().isoformat()
