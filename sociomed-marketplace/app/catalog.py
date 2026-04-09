"""
CatalogEngine — reads the Excel product catalog and provides fast in-memory search.
"""

import os
import logging
import threading
import time
from typing import List, Optional

import pandas as pd

logger = logging.getLogger(__name__)

RELOAD_INTERVAL_MINS = int(os.getenv("CATALOG_RELOAD_MINS", "30"))


class CatalogEngine:
    def __init__(self, path: str):
        self.path = path
        self._df = pd.DataFrame()
        self._lock = threading.RLock()
        self._load()
        self._start_reload_thread()

    def search(self, query: str, limit: int = 5) -> List[dict]:
        with self._lock:
            if self._df.empty:
                return []
            df = self._df[self._df["active"].astype(str).str.upper() == "TRUE"].copy()
            q = query.lower().strip()

            def score(row) -> int:
                name = str(row.get("name", "")).lower()
                if name == q:
                    return 4
                if q in name:
                    return 3
                search_text = " ".join([
                    str(row.get("brand", "")),
                    str(row.get("category", "")),
                    str(row.get("sub_category", "")),
                    str(row.get("tags", "")),
                    str(row.get("description", "")),
                ]).lower()
                words = q.split()
                if all(w in search_text or w in name for w in words):
                    return 2
                if any(w in search_text or w in name for w in words):
                    return 1
                return 0

            df["_score"] = df.apply(score, axis=1)
            results = (
                df[df["_score"] > 0]
                .sort_values("_score", ascending=False)
                .head(limit)
            )
            return [self._row_to_dict(r) for _, r in results.iterrows()]

    def get_by_id(self, product_id: str) -> Optional[dict]:
        with self._lock:
            if self._df.empty:
                return None
            matches = self._df[self._df["product_id"].astype(str) == str(product_id)]
            if matches.empty:
                return None
            return self._row_to_dict(matches.iloc[0])

    def get_related(self, product_id: str, limit: int = 3) -> List[dict]:
        product = self.get_by_id(product_id)
        if not product:
            return []
        related_ids = [r.strip() for r in str(product.get("related_ids", "")).split(",") if r.strip()]
        return [p for rid in related_ids[:limit] if (p := self.get_by_id(rid))]

    def reload(self):
        self._load()

    def _load(self):
        try:
            df = pd.read_excel(self.path, sheet_name="products", dtype=str)
            df.columns = [c.strip().lower().replace(" ", "_") for c in df.columns]
            for col in ("price_ugx", "price_usd", "lead_days", "min_order_qty"):
                if col in df.columns:
                    df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)
            with self._lock:
                self._df = df
            logger.info(f"Catalog loaded: {len(df)} products from {self.path}")
        except FileNotFoundError:
            logger.warning(f"Catalog file not found: {self.path}")
        except Exception as e:
            logger.error(f"Catalog load failed: {e}", exc_info=True)

    def _start_reload_thread(self):
        def _runner():
            while True:
                time.sleep(RELOAD_INTERVAL_MINS * 60)
                self._load()
        threading.Thread(target=_runner, daemon=True).start()

    @staticmethod
    def _row_to_dict(row) -> dict:
        return {
            "product_id": str(row.get("product_id", "")),
            "name": str(row.get("name", "")),
            "brand": str(row.get("brand", "")),
            "category": str(row.get("category", "")),
            "sub_category": str(row.get("sub_category", "")),
            "sku": str(row.get("sku", "")),
            "unit": str(row.get("unit", "Each")),
            "currency": str(row.get("currency", "UGX")),
            "price_ugx": float(row.get("price_ugx", 0)),
            "price_usd": float(row.get("price_usd", 0)),
            "stock_status": str(row.get("stock_status", "ON_ORDER")).upper(),
            "lead_days": int(float(row.get("lead_days", 3))),
            "min_order_qty": int(float(row.get("min_order_qty", 1))),
            "tags": str(row.get("tags", "")),
            "related_ids": str(row.get("related_ids", "")),
            "description": str(row.get("description", "")),
        }
