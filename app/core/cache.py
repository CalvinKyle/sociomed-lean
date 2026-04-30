import json
import redis
from typing import Dict, Any
import logging

from app.core.sheet_sync import split_multi_value_cell
from app.core.config import CACHE_TTL_SECONDS, build_redis_url
from app.models.db import load_data   # This pulls the full dataset from PostgreSQL

logger = logging.getLogger(__name__)

# Global Redis client (created once when the module is imported)
redis_client = redis.Redis.from_url(
    build_redis_url(),
    decode_responses=True,      # Automatically converts bytes to str
    socket_timeout=5,
    socket_connect_timeout=5,
    retry_on_timeout=True
)

CACHE_KEY = "sociomed:full_data"   # All products, inventory, pricing, etc.


def _build_search_documents(data: dict) -> list[dict]:
    products_by_id = {product["product_id"]: product for product in data.get("products", [])}
    aliases_by_product = {}
    for alias in data.get("aliases", []):
        product_id = alias.get("product_id")
        alias_text = alias.get("alias")
        if product_id and alias_text:
            aliases_by_product.setdefault(product_id, []).append(alias_text)

    skus_by_product = {}
    for inventory_item in data.get("inventory", []):
        product_id = inventory_item.get("product_id")
        sku = inventory_item.get("sku")
        if product_id and sku:
            skus_by_product.setdefault(product_id, []).append(sku)

    documents = []
    for product_id, product in products_by_id.items():
        documents.append(
            {
                "product_id": product_id,
                "fields": [
                    {"name": "alias", "weight": 1.25, "values": aliases_by_product.get(product_id, [])},
                    {"name": "name", "weight": 1.15, "values": [product.get("name", "")]},
                    {"name": "clinical_speciality", "weight": 0.95, "values": split_multi_value_cell(product.get("clinical_speciality"))},
                    {"name": "category", "weight": 0.75, "values": [product.get("category", "")]},
                    {"name": "sku", "weight": 0.8, "values": skus_by_product.get(product_id, [])},
                ],
            }
        )
    return documents


def _build_related_product_indexes(data: dict) -> None:
    related_by_product = {}
    reverse_related_by_product = {}

    for product in data.get("products", []):
        product_id = product.get("product_id")
        if not product_id:
            continue
        related_ids = [
            related_id
            for related_id in split_multi_value_cell(product.get("related_ids"))
            if related_id and related_id != product_id
        ]
        related_by_product[product_id] = related_ids
        for related_id in related_ids:
            reverse_related_by_product.setdefault(related_id, []).append(product_id)

    data["related_by_product"] = related_by_product
    data["reverse_related_by_product"] = reverse_related_by_product


def build_indexes(data: dict) -> dict:
    """Pre-build lookup indexes to avoid O(n) loops on every search."""
    data["products_by_id"] = {p["product_id"]: p for p in data.get("products", [])}

    data["inventory_by_product"] = {}
    for inv in data.get("inventory", []):
        pid = inv["product_id"]
        data["inventory_by_product"].setdefault(pid, []).append(inv)

    data["vendors_by_id"] = {v["vendor_id"]: v for v in data.get("vendors", [])}

    data["pricing_by_inventory"] = {}
    for pr in data.get("pricing", []):
        iid = pr["inventory_id"]
        data["pricing_by_inventory"].setdefault(iid, []).append(pr)

    data["search_documents"] = _build_search_documents(data)
    _build_related_product_indexes(data)

    return data

def get_cached_data() -> Dict[str, Any]:
    """
    Returns the full dataset (products, vendors, inventory, pricing, aliases)
    from Redis cache if available, otherwise loads from PostgreSQL and caches it.
    """
    # 1. Try Redis first (super fast)
    try:
        cached = redis_client.get(CACHE_KEY)
        if cached:
            logger.debug("✅ Data loaded from Redis cache")
            return json.loads(cached)
    except Exception as e:
        logger.warning(f"Redis cache read failed: {e}. Falling back to DB.")

    # 2. Fallback: Load fresh data from PostgreSQL
    logger.info("📥 Loading data from PostgreSQL (cache miss)")
    data = build_indexes(load_data())

    # 3. Cache the result for future requests
    try:
        redis_client.setex(
            CACHE_KEY,
            CACHE_TTL_SECONDS,          # e.g. 300 seconds = 5 minutes
            json.dumps(data)
        )
        logger.info("✅ Data cached in Redis")
    except Exception as e:
        logger.warning(f"Failed to cache data in Redis: {e}")

    return data

# Optional helper if you ever need to clear the cache manually
def clear_cache() -> bool:
    """Clear the full dataset cache (useful after sync_sheets_to_db.py runs)."""
    try:
        redis_client.delete(CACHE_KEY)
        logger.info("🗑️ Full data cache cleared")
        return True
    except Exception as e:
        logger.error(f"Failed to clear cache: {e}")
        return False
